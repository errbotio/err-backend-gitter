#!/usr/bin/env python3

import requests
from urllib.parse import urlencode
import bottle
import sys
import threading
import webbrowser
import os
import signal

@bottle.route('/')
def oauth_callback():
    code = bottle.request.query.code
    print("Receive code %s from gitter" % code)
    payload = {'client_id': CLIENT_ID,
               'client_secret': CLIENT_SECRET,
               'code': code,
               'redirect_uri':'http://localhost:8080/',
               'grant_type': 'authorization_code',
               'expires_in': 86400 * 365,
               }

    headers = {'Accept': 'application/json'}
    response = requests.post("https://gitter.im/login/oauth/token", data=payload)
    content = response.json()
    if 'error' in content:
      print('There has been a problem, gitter responded:')
      print(content['error_description'])
      sys.exit(-1)
    token = content['access_token']
    print('Full response (debug purposes): %s' % repr(content))
    print()
    print()
    print('You need to put:\nOAUTH_TOKEN=%s\nin your BOT_IDENTITY section of your config.py.' % token)
    threading.Timer(3.0, lambda:os.kill(os.getpid(), signal.SIGTERM)).start()
    return '<html><body>You need to put:<br/>OAUTH_TOKEN=%s<br/>in your BOT_IDENTITY section of your config.py.</body></html>' % token

print('Welcome to the gitter oauth 2 authenticator for err.')
print()
print('Go to https://developer.gitter.im/apps.')
print('For `Name` any name name: errbot, err....')
print('For `Redirect URL` copy paste: http://localhost:8080/')
print('The site will give you back the necessary information.')
print()

CLIENT_ID = input("Enter the OAUTH KEY:")
CLIENT_SECRET = input("Enter the OAUTH SECRET:")

init_payload = {'client_id': CLIENT_ID,
                'response_type': 'code',
                'redirect_uri': 'http://localhost:8080/'}

# make initial url
url = "https://gitter.im/login/oauth/authorize?" + urlencode(init_payload)
print ('Now point your browser to:\n%s\nto authorize Err to use gitter. I\'ll try to spawn your browser locally if possible.' % url)
webbrowser.open_new_tab('%s' % url)
bottle.run(host='localhost', port=8080)

