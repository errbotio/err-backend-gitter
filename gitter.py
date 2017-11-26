from errbot.errBot import ErrBot
import json
import logging
import time
import random
import requests
import sys
import threading
from errbot.backends.base import Message, Person, Room, RoomOccupant
from errbot.rendering import md

# Can't use __name__ because of Yapsy
log = logging.getLogger('errbot.backends.gitter')

# This limit wasn't published anywhere at time of implementation,
# but experimentation showed that 4096 was the absolute maximum
# length allowed. Anything higher would return "400 Bad Request".
GITTER_MESSAGE_SIZE_LIMIT = 4096


class GitterBackendException(Exception):
    """Generic exception class for exceptions raised by the Gitter backend"""


class MissingRoomAttributeError(GitterBackendException):
    """Raised when an identifier is missing the expected room attribute"""

class RoomNotFoundError(GitterBackendException):
    """Raised when room is not found on querying the room resource"""


class GitterPerson(Person):
    def __init__(self,
                 idd=None,
                 username=None,
                 displayName=None,
                 url=None,
                 avatarSmall=None,
                 avatarMedium=None):
        self._idd = idd
        self._username = username
        self._displayName = displayName
        self._url = url
        self._avatarSmall = avatarSmall
        self._avatarMedium = avatarMedium

    @property
    def idd(self):
        return self._idd

    @property
    def username(self):
        return self._username

    @property
    def displayName(self):
        return self._displayName

    @property
    def url(self):
        return self._url

    @property
    def avatarSmall(self):
        return self._avatarSmall

    @property
    def avatarMedium(self):
        return self._avatarMedium

    # Generic API
    @property
    def person(self):
        return self._idd

    @property
    def nick(self):
        return self._username

    @property
    def fullname(self):
        return self._displayName

    @property
    def client(self):
        return ''

    @staticmethod
    def build_from_json(from_user):
        return GitterPerson(idd=from_user['id'],
                            username=from_user['username'],
                            displayName=from_user['displayName'],
                            url=from_user['url'],
                            avatarSmall=from_user['avatarUrlSmall'],
                            avatarMedium=from_user['avatarUrlMedium'])

    def __eq__(self, other):
        return str(self) == str(other)

    def __unicode__(self):
        return self.username

    __str__ = __unicode__
    aclattr = nick


class GitterRoomOccupant(GitterPerson, RoomOccupant):
    def __init__(self,
                 room,
                 idd=None,
                 username=None,
                 displayName=None,
                 url=None,
                 avatarSmall=None,
                 avatarMedium=None):
        self._room = room
        super().__init__(idd,
                         username,
                         displayName,
                         url,
                         avatarSmall,
                         avatarMedium)

    @property
    def room(self):
        return self._room

    @staticmethod
    def build_from_json(room, json_user):
        return GitterRoomOccupant(room,
                                  idd=json_user['id'],
                                  username=json_user['username'],
                                  displayName=json_user['displayName'],
                                  url=json_user['url'],
                                  avatarSmall=json_user['avatarUrlSmall'],
                                  avatarMedium=json_user['avatarUrlMedium'])

    def __unicode__(self):
        if self.url == self._room._uri:
            return self.username  # this is a 1 to 1 MUC
        return self.username + '@' + self._room.name

    def __eq__(self, other):
        if hasattr(other, 'person'):
            return self.person == other.person
        return str(self) == str(other)

    __str__ = __unicode__


class GitterRoom(Room):

    def invite(self, *args) -> None:
        pass

    def __init__(self, backend, idd, uri, name):
        self._backend = backend
        self._name = name
        self._uri = uri
        self._idd = idd
        self._joined = False

    def join(self, username=None, password=None):
        log.debug("Joining room %s (%s)" % (self._uri, self._idd))
        try:
            response = self._backend.writeAPIRequest('rooms', {'uri': self._uri})
            log.debug("Response: %s" % response)
        except Exception:
            log.exception("Failed to join room")
        self._backend.follow_room(self)

    @property
    def uri(self):
        return self._uri

    @property
    def idd(self):
        return self._idd

    @property
    def name(self):
        return self._name

    @property
    def joined(self):
        return self._joined

    exists = True  # TODO

    def destroy(self):
        pass  # TODO

    def create(self):
        pass  # TODO

    def leave(self, reason=None):
        pass  # TODO

    @property
    def topic(self):
        json = self._backend.readAPIRequest('rooms', {"q": self.uri}).json()
        for element in json:
            if element.uri == self.uri:
                return element.topic
            else:
                raise RoomNotFoundError("Cannot find the room '{}'".format(self.uri))

    @property
    def occupants(self):
        occupants = []
        json_users = self._backend.readAPIRequest('rooms/%s/users' % self._uri)
        for json_user in json_users:
            occupants.append(GitterRoomOccupant.build_from_json(self, json_user['id']))
        return occupants

    def __eq_(self, other):
        return str(self) == str(other)

    def __unicode__(self):
        return self.name

    __str__ = __unicode__

class GitterRoomThread(threading.Thread):
    def __init__(self, room, backend):
        super().__init__()
        self.room = room
        self.backend = backend
        self._reconnection_count = 0          # Increments with each failed (re)connection
        self._reconnection_delay = 1          # Amount of seconds the bot will sleep on the
        #                                     # next reconnection attempt
        self._reconnection_max_delay = 600    # Maximum delay between reconnection attempts
        self._reconnection_multiplier = 1.75  # Delay multiplier
        self._reconnection_jitter = (0, 3)    # Random jitter added to delay (min, max)

    def run(self):
        self.room._joined = True
        log.debug("thread for %s started" % self.room.idd)
        while True:
            self.stream()
            self._delay_reconnect()

    def _delay_reconnect(self):
        """Delay next reconnection attempt until a suitable back-off time has passed"""
        time.sleep(self._reconnection_delay)

        self._reconnection_delay *= self._reconnection_multiplier
        if self._reconnection_delay > self._reconnection_max_delay:
            self._reconnection_delay = self._reconnection_max_delay
        self._reconnection_delay += random.uniform(*self._reconnection_jitter)  # nosec

    def reset_reconnection_count(self) -> None:
        """
        Reset the reconnection count. Back-ends should call this after
        successfully connecting.
        """
        self._reconnection_count = 0
        self._reconnection_delay = 1

    def stream(self):
        r = self.backend.streamAPIRequest('rooms/%s/chatMessages' % self.room.idd)
        log.debug("connected %s" % self.room.name)

        try:
            self.reset_reconnection_count()
            for line in r.iter_lines(chunk_size=1):  # it fails with anything else than 1.
                if line.strip():
                    json_message = json.loads(line.decode('utf-8'))
                    from_user = json_message['fromUser']
                    log.debug("Raw message from room %s: %s" % (self.room.name, json_message))
                    m = Message(json_message['text'],
                                extras={'id': json_message['id']})
                    if self.room._uri == from_user['url']:
                        m.to = self.backend.bot_identifier
                    else:
                        m.to = self.room
                        m.extras['url'] = 'https://gitter.im/%s?at=%s' % (
                            self.room.uri, m.extras['id'])
                    m.frm = GitterRoomOccupant.build_from_json(self.room, from_user)
                    self.backend.callback_message(m)
                else:
                    log.debug('Received keep-alive on %s', self.room.name)
        except:
            log.exception('An exception occured while streaming the room: ')

class GitterBackend(ErrBot):
    """
    This is the Gitter backend for errbot.
    """

    def __init__(self, config):
        super().__init__(config)
        if config.MESSAGE_SIZE_LIMIT > GITTER_MESSAGE_SIZE_LIMIT:
            log.info(
                "Capping MESSAGE_SIZE_LIMIT to %s which is the maximum length allowed by Gitter",
                GITTER_MESSAGE_SIZE_LIMIT
            )
            config.MESSAGE_SIZE_LIMIT = GITTER_MESSAGE_SIZE_LIMIT
        self.md = md()
        identity = config.BOT_IDENTITY

        self.token = identity.get('token', None)
        self.rooms_to_join = config.CHATROOM_PRESENCE

        if not self.token:
            log.fatal(
                    'You need to set your auth token in the BOT_IDENTITY setting of '
                    'your configuration. To obtain it, execute the included oauth.py '
                    'script'
            )
            sys.exit(1)
        self.base_headers = {'Authorization': 'Bearer ' + self.token,
                             'Accept': 'application/json'}
        self.bot_identifier = self._get_bot_identifier()

        self._joined_rooms_lock = threading.Lock()
        self._joined_rooms = []

    def _get_bot_identifier(self):
        """
        Query the API for the bot's own identifier.
        """
        log.debug("Fetching and building identifier for the bot itself.")
        r = self.readAPIRequest('user')
        assert len(r) == 1
        bot_identifier = GitterPerson.build_from_json(r[0])
        log.debug("Done! I'm connected as %s", bot_identifier)
        return bot_identifier

    def readAPIRequest(self, endpoint, params=None):
        r = requests.get('https://api.gitter.im/v1/' + endpoint, headers=self.base_headers, params=params)
        if r.status_code != requests.codes.ok:
            raise Exception("Server returned an error %d:%s" % (r.status_code, r.text))
        return r.json()

    def streamAPIRequest(self, endpoint, params=None):
        r = requests.get('https://stream.gitter.im/v1/' + endpoint, headers=self.base_headers, params=params,
                         stream=True)
        if r.status_code != requests.codes.ok:
            raise Exception("Server returned an error %d:%s" % (r.status_code, r.text))
        return r

    def writeAPIRequest(self, endpoint, content):
        headers = self.base_headers.copy()
        headers['Content-Type'] = 'application/json'
        data = json.dumps(content)
        log.debug("POST url= %s, data = %s" % ('https://api.gitter.im/v1/' + endpoint, data))
        r = requests.post('https://api.gitter.im/v1/' + endpoint, headers=headers, data=data)

        if r.status_code != requests.codes.ok:
            raise Exception("Server returned an error %d:%s" % (r.status_code, r.text))
        return r.json()

    def follow_room(self, room):
        log.debug("following room %s" % room._idd)
        if room._uri not in self._joined_rooms:
            thread = GitterRoomThread(room, self)
            thread.daemon = True
            thread.start()
            with self._joined_rooms_lock:
                self._joined_rooms.append(room._uri)
        else:
            log.info("Already joined %s", room.name)

    def rooms(self):
        json_rooms = self.readAPIRequest('rooms')
        rooms = []
        for json_room in json_rooms:
            if not json_room['oneToOne']:
                log.debug("found room %s (%s)" % (json_room['name'], json_room['uri']))
                rooms.append(GitterRoom(self, json_room['id'], json_room['uri'],
                                        json_room['name']))
        return rooms

    def contacts(self):
        # contacts are a kind of special Room
        json_rooms = self.readAPIRequest('rooms')
        contacts = []
        for json_room in json_rooms:
            if json_room['oneToOne']:
                json_user = json_room['user']
                log.debug("found contact %s" % repr(json_room))
                contacts.append(
                    GitterRoom(
                        backend=self,
                        idd=json_room['id'],
                        uri=json_room['url'],
                        name=json_room['name']
                    )
                )
        return contacts

    def build_identifier(self, strrep):
        if strrep == str(self.bot_identifier):
            return self.bot_identifier

        if '@' in strrep and not strrep.startswith('@'):
            user = strrep.split('@')[0]
        else:
            user = strrep

        # contacts are a kind of special Room
        all_rooms = self.readAPIRequest('rooms')
        for json_room in all_rooms:
            if json_room['oneToOne']:
                json_user = json_room['user']
                if json_user['username'] == user:
                    return GitterRoomOccupant.build_from_json(
                        room=GitterRoom(
                            backend=self,
                            idd=json_room['id'],
                            uri=json_room['url'],
                            name=json_room['name']
                        ),
                        json_user=json_user
                    )

        room = self.query_room(strrep)
        if room is not None:
            return room

        raise Exception("Couldn't build an identifier from %s." % strrep)

    def query_room(self, room):
        # TODO: maybe we can query the room resource only
        for native_room in self.rooms():
            if native_room.uri == room:
                log.debug("Found room %s" % room)
                return native_room
        return None

    def send_message(self, mess):
        super().send_message(mess)
        log.debug("bf body = %s" % mess.body)
        body = self.md.convert(mess.body)  # strips the unsupported stuff.
        log.debug("af body = %s" % body)
        content = {'text': body}
        if hasattr(mess.to, 'room'):
            self.writeAPIRequest('rooms/%s/chatMessages' % mess.to.room.idd,
                                 content)
        else:
            raise MissingRoomAttributeError('Unable to send message, `mess.to.room` is not present.')

    def build_reply(self, mess, text=None, private=False, threaded=False):
        response = self.build_message(text)
        response.frm = mess.to
        response.to = mess.frm
        if private:
            response.to = self.build_identifier(mess.frm.nick)
        return response

    def connect_callback(self):
        super().connect_callback()

        # listen to the one to one contacts
        # TODO: update that when a new contact adds you up
        for contact_room in self.contacts():
            self.follow_room(contact_room)

    def serve_once(self):
        self.connect_callback()
        try:
            while True:
                time.sleep(2)
        except KeyboardInterrupt:
            log.info("Interrupt received, shutting down..")
            return True
        finally:
            self.disconnect_callback()

    def change_presence(self, status, message):
        log.warn("Presence is not implemented on the gitter backend.")
        pass

    def prefix_groupchat_reply(self, message, identifier):
        message.body = '{0}: {1}'.format(identifier.nick, message.body)

    @property
    def mode(self):
        return 'gitter'
