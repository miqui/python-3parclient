# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2012 Hewlett Packard Development Company, L.P.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""
HP3Par HTTP Client
"""

import logging
import os
import urlparse
import httplib2
import time
import pprint

try:
    import json
except ImportError:
    import simplejson as json

from hp3parclient import exceptions

class HTTPRESTClient(httplib2.Http):

    USER_AGENT = 'python-3parclient'

    def __init__(self, api_url=None,
                 insecure=False, timeout=None, 
                 timings=False, no_cache=False, 
                 http_log_debug=False):
        super(HTTPRESTClient, self).__init__(timeout=timeout)

        self.session_key = None

	#should be http://<Server:Port>/api/v1
        self.api_url = api_url.rstrip('/')
	self.set_debug_flag(http_log_debug)

        self.times = []  # [("item", starttime, endtime), ...]

        # httplib2 overrides
        self.force_exception_to_status_code = True
        self.disable_ssl_certificate_validation = insecure

        self._logger = logging.getLogger(__name__)

    def set_debug_flag(self, flag):
	self.http_log_debug = flag
        if self.http_log_debug:
            ch = logging.StreamHandler()
            self._logger.setLevel(logging.DEBUG)
            self._logger.addHandler(ch)

    def authenticate(self, user, password):
        #this prevens re-auth attempt if auth fails
	self.auth_try = 1
        info = {'user':user, 'password':password}
        resp, body = self.post('/credentials', body=info)
        if body and 'key' in body:
            self.session_key = body['key']
	self.auth_try = 0
        self.user = user
	self.password = password

    def _reauth(self):
	self.authenticate(self.user, self.password)
        

    def unauthenticate(self):
        """Forget all of our authentication information."""
	#delete the session on the 3Par
        self.delete('/credentials/%s' % self.session_key)
        self.session_key = None

    def get_timings(self):
        return self.times

    def reset_timings(self):
        self.times = []

    def http_log_req(self, args, kwargs):
        if not self.http_log_debug:
            return

        string_parts = ['curl -i']
        for element in args:
            if element in ('GET', 'POST'):
                string_parts.append(' -X %s' % element)
            else:
                string_parts.append(' %s' % element)

        for element in kwargs['headers']:
            header = ' -H "%s: %s"' % (element, kwargs['headers'][element])
            string_parts.append(header)

        self._logger.debug("\nREQ: %s\n" % "".join(string_parts))
        if 'body' in kwargs:
            self._logger.debug("REQ BODY: %s\n" % (kwargs['body']))

    def http_log_resp(self, resp, body):
        if not self.http_log_debug:
            return
        self._logger.debug("RESP:%s\n", pprint.pformat(resp))
        self._logger.debug("RESP BODY:%s\n", body)

    def request(self, *args, **kwargs):
        kwargs.setdefault('headers', kwargs.get('headers', {}))
        kwargs['headers']['User-Agent'] = self.USER_AGENT
        kwargs['headers']['Accept'] = 'application/json'
        if 'body' in kwargs:
            kwargs['headers']['Content-Type'] = 'application/json'
            kwargs['body'] = json.dumps(kwargs['body'])

        self.http_log_req(args, kwargs)
        resp, body = super(HTTPRESTClient, self).request(*args, **kwargs)
        self.http_log_resp(resp, body)
       
	try:
	    if 'x-informapi-sessionkey' in resp:
	        self.session_key = resp['x-informapi-sessionkey']
	except Exception as ex:
	    pprint.pprint(ex)
	    #there was no header, so we won't save it.
            pass

        if body:
            try:
                body = json.loads(body)
            except ValueError:
                #pprint.pprint("failed to decode json\n")
                pass
        else:
            body = None

        if resp.status >= 400:
            raise exceptions.from_response(resp, body)

        return resp, body

    def _time_request(self, url, method, **kwargs):
        start_time = time.time()
        resp, body = self.request(url, method, **kwargs)
        self.times.append(("%s %s" % (method, url),
                           start_time, time.time()))
        return resp, body


    def _cs_request(self, url, method, **kwargs):
        # Perform the request once. If we get a 401 back then it
        # might be because the auth token expired, so try to
        # re-authenticate and try again. If it still fails, bail.
        try:
            if self.session_key:
                kwargs.setdefault('headers', {})['X-InFormAPI-SessionKey'] = self.session_key

            resp, body = self._time_request(self.api_url + url, method,
                                            **kwargs)
            return resp, body
        except exceptions.Unauthorized, ex:
            try:
		if self.auth_try != 1:
                    self.reauth()
                    resp, body = self._time_request(self.management_url + url, method, **kwargs)
                    return resp, body
                else:
                    raise ex
            except exceptions.Unauthorized:
                raise ex

    def get(self, url, **kwargs):
        return self._cs_request(url, 'GET', **kwargs)

    def post(self, url, **kwargs):
        return self._cs_request(url, 'POST', **kwargs)

    def put(self, url, **kwargs):
        return self._cs_request(url, 'PUT', **kwargs)

    def delete(self, url, **kwargs):
        return self._cs_request(url, 'DELETE', **kwargs)