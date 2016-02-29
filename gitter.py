from errbot.errBot import ErrBot
import json
import logging
import time
import requests
import sys
import threading
from errbot.backends.base import Message, MUCRoom
from errbot.rendering import md

# Can't use __name__ because of Yapsy
log = logging.getLogger('errbot.backends.gitter')

# This limit wasn't published anywhere at time of implementation,
# but experimentation showed that 4096 was the absolute maximum
# length allowed. Anything higher would return "400 Bad Request".
GITTER_MESSAGE_SIZE_LIMIT = 4096


class GitterIdentifier(object):
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
        return GitterIdentifier(idd=from_user['id'],
                                username=from_user['username'],
                                displayName=from_user['displayName'],
                                url=from_user['url'],
                                avatarSmall=from_user['avatarUrlSmall'],
                                avatarMedium=from_user['avatarUrlMedium'])

    def __unicode__(self):
        return self.username

    aclattr = nick


class GitterMUCOccupant(GitterIdentifier):
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
        return GitterMUCOccupant(room,
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

    __str__ = __unicode__


class GitterRoom(MUCRoom):

    def invite(self, *args) -> None:
        pass

    def __init__(self, backend, idd, uri, name):
        self._backend = backend
        self._name = name
        self._uri = uri
        self._idd = idd

    def join(self, username=None, password=None):
        log.debug("Joining room %s (%s)" % (self._uri, self._idd))
        try:
            response = self._backend.writeAPIRequest('rooms', {'uri': self._uri})
            log.debug("Response: %s" % response)
        except Exception as e:
            log.exception("Failed to join room")
        self._backend.follow_room(self)

    @property
    def uri(self):
        return self._uri

    @property
    def idd(self):
        return self._idd

    # make a Room compatible with an identifier
    to = idd
    person = to

    @property
    def name(self):
        return self._name

    joined = True  # TODO
    exists = True  # TODO

    def destroy(self):
        pass  # TODO

    def create(self):
        pass  # TODO

    def leave(self):
        pass  # TODO

    @property
    def topic(self):
        return "TODO"  # TODO

    @property
    def occupants(self):
        occupants = []
        json_users = self._backend.readAPIRequest('rooms/%s/users' % self._uri)
        for json_user in json_users:
            occupants.append(GitterMUCOccupant.build_from_json(self, json_user['id']))

    def __unicode__(self):
        return self.name

    __str__ = __unicode__


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
        self.bot_identifier = GitterIdentifier(username='Errbot # this is unused in Gitter')
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

        def background():
            log.debug("thread for %s started" % room.idd)
            r = self.streamAPIRequest('rooms/%s/chatMessages' % room.idd)
            log.debug("connected %s" % room.name)
            for line in r.iter_lines(chunk_size=1):  # it fails with anything else than 1.
                if line.strip():
                    json_message = json.loads(line.decode('utf-8'))
                    from_user = json_message['fromUser']
                    log.debug("Raw message from room %s: %s" % (room.name, json_message))
                    if room._uri == from_user['url']:
                        m = Message(json_message['text'], type_='chat')
                    else:
                        m = Message(json_message['text'], type_='groupchat')
                    m.frm = GitterMUCOccupant.build_from_json(room, from_user)
                    m.to = self.bot_identifier
                    self.callback_message(m)
                else:
                    log.debug('keep alive')

        t = threading.Thread(target=background)
        t.daemon = True
        t.start()

    def rooms(self):
        json_rooms = self.readAPIRequest('rooms')
        rooms = []
        for json_room in json_rooms:
            if not json_room['oneToOne']:
                log.debug("found room %s (%s)" % (json_room['name'], json_room['uri']))
                rooms.append(GitterRoom(self, json_room['id'], json_room['uri'], json_room['name']))
        return rooms

    def contacts(self):
        # contacts are a kind of special Room
        json_rooms = self.readAPIRequest('rooms')
        contacts = []
        for json_room in json_rooms:
            if json_room['oneToOne']:
                json_user = json_room['user']
                log.debug("found contact %s" % repr(json_room))
                contacts.append(GitterRoom(self, json_room['id'], json_room['url'], json_room['name']))
        return contacts

    def build_identifier(self, strrep):
        # contacts are a kind of special Room
        all_rooms = self.readAPIRequest('rooms')
        for json_room in all_rooms:
            if json_room['oneToOne']:
                json_user = json_room['user']
                if json_user['username'] == strrep:
                    return GitterIdentifier.build_from_json(json_user)
        raise Exception("%s not found in %s", (strrep, all_rooms))

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
            log.warn('unable to send this message, mess.to.room is not specified.')

    def build_reply(self, mess, text=None, private=False):
        response = self.build_message(text)
        response.frm = mess.to
        response.to = mess.frm
        response.type = 'chat' if private else mess.type
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
