from abc import ABC, abstractmethod
from owrx.config import CoreConfig
import json

import logging

logger = logging.getLogger(__name__)


class PasswordException(Exception):
    pass


class Password(ABC):
    @staticmethod
    def from_dict(d: dict):
        if "encoding" not in d:
            raise PasswordException("password encoding not set")
        if d["encoding"] == "string":
            return CleartextPassword(d)
        raise PasswordException("invalid passord encoding: {0}".format(d["type"]))

    @abstractmethod
    def is_valid(self, inp: str):
        pass

    @abstractmethod
    def toJson(self):
        pass


class CleartextPassword(Password):
    def __init__(self, pwinfo):
        if isinstance(pwinfo, str):
            self._value = pwinfo
        elif isinstance(pwinfo, dict):
            self._value = pwinfo["value"]
        else:
            raise ValueError("invalid argument to ClearTextPassword()")

    def is_valid(self, inp: str):
        return self._value == inp

    def toJson(self):
        return {
            "encoding": "string",
            "value": self._value
        }


DefaultPasswordClass = CleartextPassword


class User(object):
    def __init__(self, name: str, enabled: bool, password: Password):
        self.name = name
        self.enabled = enabled
        self.password = password

    def toJson(self):
        return {
            "user": self.name,
            "enabled": self.enabled,
            "password": self.password.toJson()
        }


class UserList(object):
    sharedInstance = None

    @staticmethod
    def getSharedInstance():
        if UserList.sharedInstance is None:
            UserList.sharedInstance = UserList()
        return UserList.sharedInstance

    def __init__(self):
        self.users = self._loadUsers()

    def _getUsersFile(self):
        config = CoreConfig()
        return "{data_directory}/users.json".format(data_directory=config.get_data_directory())

    def _loadUsers(self):
        usersFile = self._getUsersFile()
        try:
            with open(usersFile, "r") as f:
                users_json = json.load(f)

            return {u.name: u for u in [self._jsonToUser(d) for d in users_json]}
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            logger.exception("error while parsing users file %s", usersFile)
            return {}
        except Exception:
            logger.exception("error while processing users from %s", usersFile)
            return {}

    def _jsonToUser(self, d):
        if "user" in d and "password" in d and "enabled" in d:
            return User(d["user"], d["enabled"], Password.from_dict(d["password"]))

    def _userToJson(self, u):
        return u.toJson()

    def _store(self):
        usersFile = self._getUsersFile()
        users = [u.toJson() for u in self.users.values()]
        try:
            with open(usersFile, "w") as f:
                json.dump(users, f, indent=4)
        except Exception:
            logger.exception("error while writing users file %s", usersFile)

    def addUser(self, user: User):
        self[user.name] = user

    def deleteUser(self, user):
        if isinstance(user, User):
            username = user.name
        else:
            username = user
        del self[username]

    def __delitem__(self, key):
        if key not in self.users:
            raise KeyError("User {user} doesn't exist".format(user=key))
        del self.users[key]
        self._store()

    def __getitem__(self, item):
        return self.users[item]

    def __contains__(self, item):
        return item in self.users

    def __setitem__(self, key, value):
        if key in self.users:
            raise KeyError("User {user} already exists".format(user=key))
        self.users[key] = value
        self._store()
