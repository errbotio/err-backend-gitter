from errbot.errBot import ErrBot
import json
import logging
import time
import requests
import sys
import threading
from errbot.backends.base import Message, Presence, Stream, MUCRoom

log = logging.getLogger(__name__)


class GitterIdentifier(object):
    def __init__(self,
                 idd=None,
                 username=None,
                 displayName=None,
                 url=None,
                 avatarSmall=None,
                 avatarMedium=None):
      self._idd = idd
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
    def person(self):
      return self.username

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

class GitterRoom(MUCRoom):
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

    @property
    def name(self):
      return self._name

    joined = True  #TODO
    exists = True  #TODO

    def destroy(self):
      pass #TODO

    def create(self):
      pass #TODO

    def leave(self):
      pass #TODO

    @property
    def topic(self):
      return "TODO" #TODO

    @property
    def occupants(self):
      occupants = []
      json_users = self._backend.readAPIRequest('rooms/%s/users' % self._uri)
      for json_user in json_users:
        occupants.append(GitterMUCOccupant(self,
                                           idd=json_user['id'],
                                           username=json_user['username'],
                                           displayName=json_user['displayName'],
                                           url=json_user['url'],
                                           avatarSmall=json_user['avatarUrlSmall'],
                                           avatarMedium=json_user['avatarUrlMedium']))


class GitterBackend(ErrBot):

    def __init__(self, config):
        super().__init__(config)
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
        r = requests.get('https://api.gitter.im/v1/' + endpoint, headers=self.base_headers, params = params)
        if r.status_code != requests.codes.ok:
          raise Exception("Server returned an error %d:%s" % (r.status_code, r.text))
        return r.json()

    def streamAPIRequest(self, endpoint, params=None):
        r = requests.get('https://stream.gitter.im/v1/' + endpoint, headers=self.base_headers, params = params, stream=True)
        if r.status_code != requests.codes.ok:
          raise Exception("Server returned an error %d:%s" % (r.status_code, r.text))
        return r

    def writeAPIRequest(self, endpoint, content):
        headers = self.base_headers.copy()
        headers['Content-Type'] = 'application/json'
        data = json.dumps(content)
        log.debug("POST url= %s, data = %s" % ('https://api.gitter.im/v1/' + endpoint, data))
        r = requests.post('https://api.gitter.im/v1/' + endpoint, headers=headers, data = data)

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
                    m = Message(json_message['text'], type_='groupchat', html=json_message['html'])
                    m.frm = GitterMUCOccupant(room = room,
                                              idd=from_user['id'],
                                              username=from_user['username'],
                                              displayName=from_user['displayName'],
                                              url=from_user['url'],
                                              avatarSmall=from_user['avatarUrlSmall'],
                                              avatarMedium=from_user['avatarUrlMedium'])
                    m.to = self.bot_identifier
                    self.callback_message(m)
                else:
                    log.debug('keep alive')
        threading.Thread(target=background).start()

    def rooms(self):
        json_rooms = self.readAPIRequest('rooms')
        rooms = []
        for json_room in json_rooms:
          if not json_room['oneToOne']:
            log.debug("found room %s (%s)" % (json_room['name'], json_room['uri']))
            rooms.append(GitterRoom(self, json_room['id'], json_room['uri'], json_room['name']))
        return rooms

    def query_room(self, room):
        # TODO: maybe we can query the room resource only
        for native_room in self.rooms():
          if native_room.uri == room:
            log.debug("Found room %s" % room)
            return native_room
        return None

    def send_message(self, mess):
        super().send_message(mess)
        if mess.type == 'groupchat':
          self.writeAPIRequest('rooms/%s/chatMessages' % mess.to.room.idd,
                               {'text': mess.body})
    def build_reply(self, mess, text=None, private=False):
        response = Message(text, type_ = mess.type)
        response.frm = mess.to
        response.to = mess.frm
        return response
 
    def serve_forever(self):
        self.connect_callback()
        try:
            while True:
              time.sleep(2)
        finally:
            self.disconnect_callback()
            self.shutdown()

    def mode(self):
      return 'gitter'

    def groupchat_reply_format(self):
        return '@{0} {1}'
