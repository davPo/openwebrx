from owrx.map import Map, LatLngLocation
from owrx.parser import Parser
from datetime import datetime, timezone
import re
import logging
import json

logger = logging.getLogger(__name__)

# speed is in knots... convert to metric (km/h)
knotsToKilometers = 1.852

# not sure what the correct encoding is. it seems TAPR has set utf-8 as a standard, but not everybody is following it.
encoding = "utf-8"


class GpsLocation(LatLngLocation):
    def __init__(self, data):
        super().__init__(data["lat"], data["lon"])
        self.data = data

    def __dict__(self):
        res = super(GpsLocation, self).__dict__()
        for key in ["comment", "symbol", "course", "speed"]:
            if key in self.data:
                res[key] = self.data[key]
        return res

def getSymbolData(symbol, table):
    """ get APRS symbol index and table index from symbo and table
    http://www.aprs.org/doc/APRS101.PDF
    """
    return {"symbol": symbol, "table": table, "index": ord(symbol) - 33, "tableindex": ord(table) - 33}


class MicGPSParser(Parser):
    """ Parser for gpsmic_decoder executable - F1URI"""
    def __init__(self, handler):
        super().__init__(handler)

    def setDialFrequency(self, freq):
        super().setDialFrequency(freq)

    def parse(self, raw):
        try:
            my_json = raw.decode('utf8').replace("'", '"').rstrip("\n")
            # try:
            #     my_json = raw.decode('utf8').replace("'", '"').rstrip("\n")
            # except UnicodeDecodeError:
            #     return 0
            gps_data = json.loads(my_json)
            if gps_data["sats"] == 0:
                fix = 0
            else: 
                fix = 1 
            # TODO  ajouter ["type"] ["comment"] 
            micgpsData = {"symbol": getSymbolData('k', '/') , "source": gps_data['uid'], "destination": "", "path": "", "lat": gps_data['latitude'], "lon": gps_data['longitude'], "altitude":gps_data["altitude"], "course": gps_data['heading'], "speed":gps_data['speed'], "timestamp":gps_data['gpstime'], "fix":fix}
            logger.debug("decoded GPSmic data: %s", micgpsData )
            self.handler.write_gpsmic_data(micgpsData)
            self.updateMap(micgpsData)
        except Exception:
            logger.exception("exception while parsing gpsmic data")

    def updateMap(self, mapData):
        if "lat" in mapData and "lon" in mapData:
            loc = GpsLocation(mapData)
            source = mapData["source"]
            if "type" in mapData:
                if mapData["type"] == "item":
                    source = mapData["item"]
                elif mapData["type"] == "object":
                    source = mapData["object"]
            Map.getSharedInstance().updateLocation(source, loc, "MicGPS", self.band)

 


