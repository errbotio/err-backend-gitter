from errbot.errBot import ErrBot
import json
import logging
import time
import requests
import sys
from errbot.backends.base import Message, Presence, Stream, MUCRoom

log = logging.getLogger(__name__)


class GitterIdentity(object):
    def __init__(self,
                 idd=None,
                 username=None,
                 displayName=None,
                 url=None,
                 avatarSmall=None,
                 avatarMedium=None):
      self._idd = idd

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

class GitterMUCIdentity(GitterIdentity):
    def __init__(self,
                 room,
                 idd=None,
                 username=None,
                 displayName=None,
                 url=None,
                 avatarSmall=None,
                 avatarMedium=None):
      self.room = room
      super().__init__(idd,
                       username,
                       displayName,
                       url,
                       avatarSmall,
                       avatarMedium)

class GitterRoom(MUCRoom):
    def __init__(self, backend, uri, name):
        self._backend = backend
        self._name = name
        self._uri = uri

    def join(self, username=None, password=None):
      log.debug("Joining room %s" % self._uri)
      # TODO: this assume this is already joined.
      # response = self._backend.writeAPIRequest('rooms', {'uri': self._uri})
      # log.debug("Response: %s" % response)

    @property
    def uri(self):
      return self._uri

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
        occupants.append(GitterMUCIdentity(self,
                                           idd=json_user['idd'],
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

    def writeAPIRequest(self, endpoint, content):
        headers = self.base_headers.copy()
        headers['Content-Type'] = 'application/json'
        data = json.dumps(content)
        log.debug("POST url= %s, data = %s" % ('https://api.gitter.im/v1/' + endpoint, data))
        r = requests.post('https://api.gitter.im/v1/' + endpoint, headers=self.base_headers, data = data)

        if r.status_code != requests.codes.ok:
          raise Exception("Server returned an error %d:%s" % (r.status_code, r.text))
        return r.json()


    def rooms(self):
        json_rooms = self.readAPIRequest('rooms')
        rooms = []
        for json_room in json_rooms:
          if not json_room['oneToOne']:
            log.debug("found room %s (%s)" % (json_room['name'], json_room['uri']))
            rooms.append(GitterRoom(self, json_room['uri'], json_room['name']))
        return rooms

    def query_room(self, room):
        # TODO: maybe we can query the room resource only
        for native_room in self.rooms():
          if native_room.uri == room:
            log.debug("Found room %s" % room)
            return native_room
        return None

    def serve_forever(self):
        self.connect_callback()
        while True:
          time.sleep(2)

    def mode(self):
      return 'Gitter'
