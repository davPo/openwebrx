from abc import ABC, abstractmethod
from owrx.property.validators import Validator
from owrx.property.filter import Filter, ByPropertyName
import logging

logger = logging.getLogger(__name__)


class PropertyError(Exception):
    pass


class PropertyDeletion(object):
    pass


# a special object that will be sent in events when a deletion occured
# it can also represent deletion of a key in internal storage, but should not be return from standard dict apis
PropertyDeleted = PropertyDeletion()


class Subscription(object):
    def __init__(self, subscriptee, name, subscriber):
        self.subscriptee = subscriptee
        self.name = name
        self.subscriber = subscriber

    def getName(self):
        return self.name

    def call(self, *args, **kwargs):
        self.subscriber(*args, **kwargs)

    def cancel(self):
        self.subscriptee.unwire(self)


class PropertyManager(ABC):
    def __init__(self):
        self.subscribers = []

    @abstractmethod
    def __getitem__(self, item):
        pass

    @abstractmethod
    def __setitem__(self, key, value):
        pass

    @abstractmethod
    def __contains__(self, item):
        pass

    @abstractmethod
    def __dict__(self):
        pass

    @abstractmethod
    def __delitem__(self, key):
        pass

    @abstractmethod
    def keys(self):
        pass

    def items(self):
        return self.__dict__().items()

    def __len__(self):
        return self.__dict__().__len__()

    def filter(self, *props):
        return PropertyFilter(self, ByPropertyName(*props))

    def readonly(self):
        return PropertyReadOnly(self)

    def wire(self, callback):
        sub = Subscription(self, None, callback)
        self.subscribers.append(sub)
        return sub

    def wireProperty(self, name, callback):
        sub = Subscription(self, name, callback)
        self.subscribers.append(sub)
        if name in self:
            sub.call(self[name])
        return sub

    def unwire(self, sub):
        try:
            self.subscribers.remove(sub)
        except ValueError:
            # happens when already removed before
            pass
        return self

    def _fireCallbacks(self, changes):
        if not changes:
            return
        for c in self.subscribers:
            try:
                if c.getName() is None:
                    c.call(changes)
            except Exception:
                logger.exception("exception while firing changes")
        for name in changes:
            for c in self.subscribers:
                try:
                    if c.getName() == name:
                        c.call(changes[name])
                except Exception:
                    logger.exception("exception while firing changes")


class PropertyLayer(PropertyManager):
    def __init__(self, **kwargs):
        super().__init__()
        # copy, don't re-use
        self.properties = {k: v for k, v in kwargs.items()}

    def __contains__(self, name):
        return name in self.properties

    def __getitem__(self, name):
        return self.properties[name]

    def __setitem__(self, name, value):
        if name in self.properties and self.properties[name] == value:
            return
        self.properties[name] = value
        self._fireCallbacks({name: value})

    def __dict__(self):
        return {k: v for k, v in self.properties.items()}

    def __delitem__(self, key):
        self.properties.__delitem__(key)
        self._fireCallbacks({key: PropertyDeleted})

    def keys(self):
        return self.properties.keys()


class PropertyFilter(PropertyManager):
    def __init__(self, pm: PropertyManager, filter: Filter):
        super().__init__()
        self.pm = pm
        self._filter = filter
        self.pm.wire(self.receiveEvent)

    def receiveEvent(self, changes):
        changesToForward = {name: value for name, value in changes.items() if self._filter.apply(name)}
        self._fireCallbacks(changesToForward)

    def __getitem__(self, item):
        if not self._filter.apply(item):
            raise KeyError(item)
        return self.pm.__getitem__(item)

    def __setitem__(self, key, value):
        if not self._filter.apply(key):
            raise KeyError(key)
        return self.pm.__setitem__(key, value)

    def __contains__(self, item):
        if not self._filter.apply(item):
            return False
        return self.pm.__contains__(item)

    def __dict__(self):
        return {k: v for k, v in self.pm.__dict__().items() if self._filter.apply(k)}

    def __delitem__(self, key):
        if not self._filter.apply(key):
            raise KeyError(key)
        return self.pm.__delitem__(key)

    def keys(self):
        return [k for k in self.pm.keys() if self._filter.apply(k)]


class PropertyDelegator(PropertyManager):
    def __init__(self, pm: PropertyManager):
        self.pm = pm
        self.pm.wire(self._fireCallbacks)
        super().__init__()

    def __getitem__(self, item):
        return self.pm.__getitem__(item)

    def __setitem__(self, key, value):
        return self.pm.__setitem__(key, value)

    def __contains__(self, item):
        return self.pm.__contains__(item)

    def __dict__(self):
        return self.pm.__dict__()

    def __delitem__(self, key):
        return self.pm.__delitem__(key)

    def keys(self):
        return self.pm.keys()


class PropertyValidationError(PropertyError):
    def __init__(self, key, value):
        super().__init__('Invalid value for property "{key}": "{value}"'.format(key=key, value=str(value)))


class PropertyValidator(PropertyDelegator):
    def __init__(self, pm: PropertyManager, validators=None):
        super().__init__(pm)
        if validators is None:
            self.validators = {}
        else:
            self.validators = {k: Validator.of(v) for k, v in validators.items()}

    def validate(self, key, value):
        if key not in self.validators:
            return
        if not self.validators[key].isValid(value):
            raise PropertyValidationError(key, value)

    def setValidator(self, key, validator):
        self.validators[key] = Validator.of(validator)

    def __setitem__(self, key, value):
        self.validate(key, value)
        return self.pm.__setitem__(key, value)


class PropertyWriteError(PropertyError):
    def __init__(self, key):
        super().__init__('Key "{key}" is not writeable'.format(key=key))


class PropertyReadOnly(PropertyDelegator):
    def __setitem__(self, key, value):
        raise PropertyWriteError(key)


class PropertyStack(PropertyManager):
    def __init__(self):
        super().__init__()
        self.layers = []

    def addLayer(self, priority: int, pm: PropertyManager):
        """
        highest priority = 0
        """
        self._fireCallbacks(self._addLayer(priority, pm))

    def _addLayer(self, priority: int, pm: PropertyManager):
        changes = {}
        for key in pm.keys():
            if key not in self or self[key] != pm[key]:
                changes[key] = pm[key]

        def eventClosure(changes):
            self.receiveEvent(pm, changes)

        sub = pm.wire(eventClosure)

        self.layers.append({"priority": priority, "props": pm, "sub": sub})

        return changes

    def removeLayer(self, pm: PropertyManager):
        for layer in self.layers:
            if layer["props"] == pm:
                self._fireCallbacks(self._removeLayer(layer))

    def _removeLayer(self, layer):
        layer["sub"].cancel()
        self.layers.remove(layer)
        changes = {}
        pm = layer["props"]
        for key in pm.keys():
            if key in self:
                if self[key] != pm[key]:
                    changes[key] = self[key]
            else:
                changes[key] = PropertyDeleted
        return changes

    def replaceLayer(self, priority: int, pm: PropertyManager):
        layers = [x for x in self.layers if x["priority"] == priority]

        originalState = self.__dict__()

        changes = self._removeLayer(layers[0]) if layers else {}
        changes = {**changes, **self._addLayer(priority, pm)}
        changes = {k: v for k, v in changes.items() if k not in originalState or originalState[k] != v}

        self._fireCallbacks(changes)

    def receiveEvent(self, layer, changes):
        changesToForward = {name: value for name, value in changes.items() if layer == self._getTopLayer(name)}
        # deletions need to be handled separately: only send them if deleted in all layers
        deletionsToForward = {
            name: value
            for name, value in changes.items()
            if value is PropertyDeleted and self._getTopLayer(name, False) is None
        }
        self._fireCallbacks({**changesToForward, **deletionsToForward})

    def _getTopLayer(self, item, fallback=True):
        layers = [la["props"] for la in sorted(self.layers, key=lambda l: l["priority"])]
        for m in layers:
            if item in m:
                return m
        # return top layer as fallback
        if fallback and layers:
            return layers[0]

    def __getitem__(self, item):
        layer = self._getTopLayer(item)
        return layer.__getitem__(item)

    def __setitem__(self, key, value):
        layer = self._getTopLayer(key)
        return layer.__setitem__(key, value)

    def __contains__(self, item):
        layer = self._getTopLayer(item)
        if layer:
            return layer.__contains__(item)
        return False

    def __dict__(self):
        return {k: self.__getitem__(k) for k in self.keys()}

    def __delitem__(self, key):
        for layer in self.layers:
            if layer["props"].__contains__(key):
                layer["props"].__delitem__(key)

    def keys(self):
        return set([key for l in self.layers for key in l["props"].keys()])
