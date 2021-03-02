#from owrx.kiss import KissDeframer
from owrx.map import Map, LatLngLocation
from owrx.parser import Parser
from datetime import datetime, timezone
import re
import logging

logger = logging.getLogger(__name__)


# speed is in knots... convert to metric (km/h)
knotsToKilometers = 1.852

# not sure what the correct encoding is. it seems TAPR has set utf-8 as a standard, but not everybody is following it.
encoding = "utf-8"

# regex for altitute in comment field
altitudeRegex = re.compile("(^.*)\\/A=([0-9]{6})(.*$)")

# regex for parsing third-party headers
thirdpartyeRegex = re.compile("^([a-zA-Z0-9-]+)>((([a-zA-Z0-9-]+\\*?,)*)([a-zA-Z0-9-]+\\*?)):(.*)$")

# regex for getting the message id out of message
messageIdRegex = re.compile("^(.*){([0-9]{1,5})$")

# regex to filter pseudo "WIDE" path elements
widePattern = re.compile("^WIDE[0-9]-[0-9]$")


def decodeBase91(input):
    base = decodeBase91(input[:-1]) * 91 if len(input) > 1 else 0
    return base + (ord(input[-1]) - 33)

def getSymbolData(symbol, table):
    return {"symbol": symbol, "table": table, "index": ord(symbol) - 33, "tableindex": ord(table) - 33}

class AprsLocation(LatLngLocation):
    def __init__(self, data):
        super().__init__(data["lat"], data["lon"])
        self.data = data

    def __dict__(self):
        res = super(AprsLocation, self).__dict__()
        for key in ["comment", "symbol", "course", "speed"]:
            if key in self.data:
                res[key] = self.data[key]
        return res


class MicGPSParser(Parser):
    def __init__(self, handler):
        super().__init__(handler)
    #    self.ax25parser = Ax25Parser()
    #    self.deframer = KissDeframer()

    def setDialFrequency(self, freq):
        super().setDialFrequency(freq)

    def parse(self, raw):
        try:
            aprsData = {"source": "ab", "destination": "cd", "path": "ef", "lat": 46.3, "lon": 6.06, "timestamp":538457395}
            self.handler.write_gpsmic_data(aprsData)
            logger.debug("decoded APRS data: %s", aprsData)
        except Exception:
            logger.exception("exception while parsing gpsmic data")

        # for frame in self.deframer.parse(raw):
        #     try:
        #         data = self.ax25parser.parse(frame)

        #         # TODO how can we tell if this is an APRS frame at all?
        #         aprsData = self.parseAprsData(data)

        #         logger.debug("decoded APRS data: %s", aprsData)
        #         self.updateMap(aprsData)
               
        #         self.handler.write_gpsmic_data(aprsData)
        #     except Exception:
        #         logger.exception("exception while parsing gpsmic data")

    def updateMap(self, mapData):
        if "type" in mapData and mapData["type"] == "thirdparty" and "data" in mapData:
            mapData = mapData["data"]
        if "lat" in mapData and "lon" in mapData:
            loc = AprsLocation(mapData)
            source = mapData["source"]
            if "type" in mapData:
                if mapData["type"] == "item":
                    source = mapData["item"]
                elif mapData["type"] == "object":
                    source = mapData["object"]
            Map.getSharedInstance().updateLocation(source, loc, "APRS", self.band)

    def hasCompressedCoordinates(self, raw):
        return raw[0] == "/" or raw[0] == "\\"

    def parseUncompressedCoordinates(self, raw):
        lat = int(raw[0:2]) + float(raw[2:7]) / 60
        if raw[7] == "S":
            lat *= -1
        lon = int(raw[9:12]) + float(raw[12:17]) / 60
        if raw[17] == "W":
            lon *= -1
        return {"lat": lat, "lon": lon, "symbol": getSymbolData(raw[18], raw[8])}

    def parseCompressedCoordinates(self, raw):
        return {
            "lat": 90 - decodeBase91(raw[1:5]) / 380926,
            "lon": -180 + decodeBase91(raw[5:9]) / 190463,
            "symbol": getSymbolData(raw[9], raw[0]),
        }

    def parseTimestamp(self, raw):
        now = datetime.now()
        if raw[6] == "h":
            ts = datetime.strptime(raw[0:6], "%H%M%S")
            ts = ts.replace(year=now.year, month=now.month, day=now.month, tzinfo=timezone.utc)
        else:
            ts = datetime.strptime(raw[0:6], "%d%H%M")
            ts = ts.replace(year=now.year, month=now.month)
            if raw[6] == "z":
                ts = ts.replace(tzinfo=timezone.utc)
            elif raw[6] == "/":
                ts = ts.replace(tzinfo=now.tzinfo)
            else:
                logger.warning("invalid timezone info byte: %s", raw[6])
        return int(ts.timestamp() * 1000)

    def parseStatusUpate(self, raw):
        res = {"type": "status"}
        if raw[6] == "z":
            res["timestamp"] = self.parseTimestamp(raw[0:7])
            res["comment"] = raw[7:]
        else:
            res["comment"] = raw
        return res

    def parseAprsData(self, data):
        information = data["data"]

        # forward some of the ax25 data
        aprsData = {"source": data["source"], "destination": data["destination"], "path": data["path"]}

        if information[0] == 0x1C or information[0] == ord("`") or information[0] == ord("'"):
            aprsData.update(MicEParser().parse(data))
            return aprsData

        information = information.decode(encoding, "replace")

        # APRS data type identifier
        dti = information[0]

        if dti == "!" or dti == "=":
            # position without timestamp
            aprsData.update(self.parseRegularAprsData(information[1:]))
        elif dti == "/" or dti == "@":
            # position with timestamp
            aprsData["timestamp"] = self.parseTimestamp(information[1:8])
            aprsData.update(self.parseRegularAprsData(information[8:]))
        elif dti == ">":
            # status update
            aprsData.update(self.parseStatusUpate(information[1:]))
        elif dti == "}":
            # third party
            aprsData.update(self.parseThirdpartyAprsData(information[1:]))
        elif dti == ":":
            # message
            aprsData.update(self.parseMessage(information[1:]))
        elif dti == ";":
            # object
            aprsData.update(self.parseObject(information[1:]))
        elif dti == ")":
            # item
            aprsData.update(self.parseItem(information[1:]))

        return aprsData

    def parseObject(self, information):
        result = {"type": "object"}
        if len(information) > 16:
            result["object"] = information[0:9].strip()
            result["live"] = information[9] == "*"
            result["timestamp"] = self.parseTimestamp(information[10:17])
            result.update(self.parseRegularAprsData(information[17:]))
            # override type, losing information about compression
            result["type"] = "object"
        return result

    def parseItem(self, information):
        result = {"type": "item"}
        if len(information) > 3:
            indexes = [information[0:10].find(p) for p in ["!", "_"]]
            filtered = [i for i in indexes if i >= 3]
            filtered.sort()
            if len(filtered):
                index = filtered[0]
                result["item"] = information[0:index]
                result["live"] = information[index] == "!"
                result.update(self.parseRegularAprsData(information[index + 1 :]))
                # override type, losing information about compression
                result["type"] = "item"
        return result

    def parseMessage(self, information):
        result = {"type": "message"}
        if len(information) > 9 and information[9] == ":":
            result["adressee"] = information[0:9]
            message = information[10:]
            if len(message) > 3 and message[0:3] == "ack":
                result["type"] = "messageacknowledgement"
                result["messageid"] = int(message[3:8])
            elif len(message) > 3 and message[0:3] == "rej":
                result["type"] = "messagerejection"
                result["messageid"] = int(message[3:8])
            else:
                matches = messageIdRegex.match(message)
                if matches:
                    result["messageid"] = int(matches.group(2))
                    message = matches.group(1)
                result["message"] = message
        return result

    def parseThirdpartyAprsData(self, information):
        matches = thirdpartyeRegex.match(information)
        if matches:
            path = matches.group(2).split(",")
            destination = next((c.strip("*").upper() for c in path if c.endswith("*")), None)
            data = self.parseAprsData(
                {
                    "source": matches.group(1).upper(),
                    "destination": destination,
                    "path": path,
                    "data": matches.group(6).encode(encoding),
                }
            )
            return {"type": "thirdparty", "data": data}

        return {"type": "thirdparty"}

    def parseRegularAprsData(self, information):
        if self.hasCompressedCoordinates(information):
            aprsData = self.parseCompressedCoordinates(information[0:10])
            aprsData["type"] = "compressed"
            if information[10] != " ":
                if information[10] == "{":
                    # pre-calculated radio range
                    aprsData["range"] = 2 * 1.08 ** (ord(information[11]) - 33) * milesToKilometers
                else:
                    aprsData["course"] = (ord(information[10]) - 33) * 4
                    # speed is in knots... convert to metric (km/h)
                    aprsData["speed"] = (1.08 ** (ord(information[11]) - 33) - 1) * knotsToKilometers
                # compression type
                t = ord(information[12])
                aprsData["fix"] = (t & 0b00100000) > 0
                sources = ["other", "GLL", "GGA", "RMC"]
                aprsData["nmeasource"] = sources[(t & 0b00011000) >> 3]
                origins = [
                    "Compressed",
                    "TNC BText",
                    "Software",
                    "[tbd]",
                    "KPC3",
                    "Pico",
                    "Other tracker",
                    "Digipeater conversion",
                ]
                aprsData["compressionorigin"] = origins[t & 0b00000111]
            comment = information[13:]
        else:
            aprsData = self.parseUncompressedCoordinates(information[0:19])
            aprsData["type"] = "regular"
            comment = information[19:]

        def decodeHeightGainDirectivity(comment):
            res = {"height": 2 ** int(comment[4]) * 10 * feetToMeters, "gain": int(comment[5])}
            directivity = int(comment[6])
            if directivity == 0:
                res["directivity"] = "omni"
            elif 0 < directivity < 9:
                res["directivity"] = directivity * 45
            return res

        # aprs data extensions
        # yes, weather stations are officially identified by their symbols. go figure...
        if "symbol" in aprsData and aprsData["symbol"]["index"] == 62:
            # weather report
            weather = {}
            if len(comment) > 6 and comment[3] == "/":
                try:
                    weather["wind"] = {"direction": int(comment[0:3]), "speed": int(comment[4:7]) * milesToKilometers}
                except ValueError:
                    pass
                comment = comment[7:]

            parser = WeatherParser(comment, weather)
            aprsData["weather"] = parser.getWeather()
            comment = parser.getRemainder()
        elif len(comment) > 6:
            if comment[3] == "/":
                # course and speed
                # for a weather report, this would be wind direction and speed
                try:
                    aprsData["course"] = int(comment[0:3])
                    aprsData["speed"] = int(comment[4:7]) * knotsToKilometers
                except ValueError:
                    pass
                comment = comment[7:]
            elif comment[0:3] == "PHG":
                # station power and effective antenna height/gain/directivity
                try:
                    powerCodes = [0, 1, 4, 9, 16, 25, 36, 49, 64, 81]
                    aprsData["power"] = powerCodes[int(comment[3])]
                    aprsData.update(decodeHeightGainDirectivity(comment))
                except ValueError:
                    pass
                comment = comment[7:]
            elif comment[0:3] == "RNG":
                # pre-calculated radio range
                try:
                    aprsData["range"] = int(comment[3:7]) * milesToKilometers
                except ValueError:
                    pass
                comment = comment[7:]
            elif comment[0:3] == "DFS":
                # direction finding signal strength and antenna height/gain
                try:
                    aprsData["strength"] = int(comment[3])
                    aprsData.update(decodeHeightGainDirectivity(comment))
                except ValueError:
                    pass
                comment = comment[7:]

        matches = altitudeRegex.match(comment)
        if matches:
            aprsData["altitude"] = int(matches.group(2)) * feetToMeters
            comment = matches.group(1) + matches.group(3)

        aprsData["comment"] = comment

        return aprsData


