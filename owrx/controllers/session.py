from .template import WebpageController
from urllib.parse import parse_qs, urlencode
from uuid import uuid4
from http.cookies import SimpleCookie
from owrx.users import UserList


class SessionStorage(object):
    sharedInstance = None

    @staticmethod
    def getSharedInstance():
        if SessionStorage.sharedInstance is None:
            SessionStorage.sharedInstance = SessionStorage()
        return SessionStorage.sharedInstance

    def __init__(self):
        self.sessions = {}

    def generateKey(self):
        return str(uuid4())

    def startSession(self, data):
        key = self.generateKey()
        self.updateSession(key, data)
        return key

    def getSession(self, key):
        if key not in self.sessions:
            return None
        return self.sessions[key]

    def updateSession(self, key, data):
        self.sessions[key] = data


class SessionController(WebpageController):
    def loginAction(self):
        self.serve_template("login.html", **self.template_variables())

    def processLoginAction(self):
        data = parse_qs(self.get_body().decode("utf-8"))
        data = {k: v[0] for k, v in data.items()}
        userlist = UserList.getSharedInstance()
        if "user" in data and "password" in data:
            if data["user"] in userlist:
                user = userlist[data["user"]]
                if user.is_enabled() and user.password.is_valid(data["password"]):
                    key = SessionStorage.getSharedInstance().startSession({"user": user.name})
                    cookie = SimpleCookie()
                    cookie["owrx-session"] = key
                    target = self.request.query["ref"][0] if "ref" in self.request.query else "/settings"
                    if user.must_change_password:
                        target = "/pwchange?{0}".format(urlencode({"ref": target}))
                    self.send_redirect(target, cookies=cookie)
                    return
        self.send_redirect("/login")

    def logoutAction(self):
        self.send_redirect("logout happening here")
