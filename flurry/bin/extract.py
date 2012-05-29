"""
Scripted input that downloads event logs from the Flurry service.

External dependencies:
* mechanize
"""

import csv
from ConfigParser import ConfigParser
from ConfigParser import Error as ConfigError
from datetime import date, timedelta
from HTMLParser import HTMLParser
import mechanize
import os
import os.path
import re
import sys
from time import sleep

CONFIG_RELATIVE_FILEPATH = '../local/extract.conf'
CONFIG_KEYS_NEEDING_REPLACEMENT = (
    ('auth', ('email', 'password', 'project_id')),
    ('extract_position', ('year', 'month', 'day'))
)

SCRIPT_DIR = os.path.dirname(os.path.join(os.getcwd(), __file__))
CONFIG_FILEPATH = os.path.join(SCRIPT_DIR, CONFIG_RELATIVE_FILEPATH)

class RateLimitedError(Exception):
    pass

class FlurryConnection(object):
    def __init__(self, email, password, project_id):
        """
        Arguments:
        email -- email used to login.
        password -- password used to login.
        project_id -- identifier for the application, obtained from the URL
                      of the analytics dashboard page after logging in with
                      a real web browser.
        """
        self.email = email
        self.password = password
        self.project_id = project_id
    
    def login(self):
        """
        Logs in to Flurry.
        This should be invoked before any other methods.
        
        Raises:
        Exception -- if login fails for any reason.
        """
        self.browser = mechanize.Browser()
        self.browser.open('https://dev.flurry.com/secure/login.do')
        self.browser.select_form(name='loginAction')
        self.browser['loginEmail'] = self.email
        self.browser['loginPassword'] = self.password
        resp = self.browser.submit()
        
        resp_url = resp.geturl()
        success = (
            resp_url == 'https://dev.flurry.com/home.do' or
            (resp_url.startswith('https://dev.flurry.com/fullPageTakeover.do')
                and 'home.do' in resp_url))
        if not success:
            raise Exception("Couldn't login to Flurry. Redirected to %s." % 
                resp_url)
        return resp
    
    def download_log(self, yyyy, mm, dd, offset):
        """
        Downloads an individual page of events that occurred on the specified
        day, returning a file-like object containing CSV data.
        
        If the page does not exist, the returned CSV will not have any data
        rows. However it will contain an initial header row.
        
        Arguments:
        yyyy -- year.
        mm -- month (1 = January, 12 = December).
        dd -- day.
        offset -- index of the first session that will be returned.
        
        Raises:
        RateLimitedError -- if Flurry denies access due to too many requests in
                            a short time frame.
        Exception -- if the download fails for any other reason.
        """
        url = ('https://dev.flurry.com/eventsLogCsv.do?projectID=%d&' + 
            'versionCut=versionsAll&intervalCut=customInterval' + 
            '%04d_%02d_%02d-%04d_%02d_%02d&direction=1&offset=%d') % (
                self.project_id, yyyy, mm, dd, yyyy, mm, dd, offset)
        resp = self.browser.open(url)
        
        redirect_url = self.browser.geturl()
        if redirect_url != url:
            if redirect_url == 'http://www.flurry.com/rateLimit.html':
                raise RateLimitedError
            else:
                raise Exception('Redirected to unexpected location while ' + 
                    'downloading event logs: %s.' % redirect_url)
        
        return resp

UNESCAPER = HTMLParser()

def parse_params(params):
    params = params.strip('{}')
    if len(params) == 0:
        return []
    
    params_split = params.split(' : ')
    
    # Process intermediate elements (not ends)
    params_flat = []
    params_flat.append(params_split[0])
    for i in xrange(1, len(params_split)-1):
        param_split = params_split[i].rsplit(',', 1)
        if len(param_split) != 2:
            raise Exception('Could not parse intermediate parameter fragment: %s' % repr(param_split))
        params_flat.extend(param_split)
    params_flat.append(params_split[-1])
    
    if len(params_flat)%2 != 0:
        raise Exception('Expected even number of keys and values: %s' % repr(params_flat))
    
    params = []
    for i in xrange(0, len(params_flat), 2):
        params.append((params_flat[i], params_flat[i+1]))
    
    params = [(k.decode('utf-8'), v.decode('utf-8')) for (k,v) in params]
    # (unescape() expects Unicode strings)
    params = [(UNESCAPER.unescape(k), UNESCAPER.unescape(v)) for (k, v) in params]
    params = [(k.encode('utf-8'), v.encode('utf-8')) for (k,v) in params]
    
    return params

INVALID_KEY_CHAR_RE = re.compile(r'[^a-zA-Z0-9_]')

def quote_k(k):
    # Clean the key using Splunk's standard "key cleaning" rules
    # See: http://docs.splunk.com/Documentation/Splunk/4.3.2/Knowledge/
    #      Createandmaintainsearch-timefieldextractionsthroughconfigurationfiles
    return INVALID_KEY_CHAR_RE.sub('_', k)

def quote_v(v):
    return '"' + v.replace('"', "'") + '"'

class devnull(object):
    def write(self, value):
        pass
    
    def flush(self):
        pass

output = (
    sys.stdout
    #devnull()
)
log = (
    #sys.stderr
    devnull()
)

# -----------------------------------------------------------------------------

config = ConfigParser()
config.read(CONFIG_FILEPATH)

def config_flush():
    with open(CONFIG_FILEPATH, 'wb') as config_stream:
        config.write(config_stream)

# Ensure configuration looks valid
for (section, keys) in CONFIG_KEYS_NEEDING_REPLACEMENT:
    for key in keys:
        value = config.get(section, key)
        if value.startswith('__') and value.endswith('__'):
            raise ConfigError('Missing configuration value %s/%s in %s' %
                (section, key, CONFIG_FILEPATH))

did_login = False
rate_limited_on_last_request = False
while True:
    (year, month, day, offset) = (
        int(config.get('extract_position', 'year')),
        int(config.get('extract_position', 'month')),
        int(config.get('extract_position', 'day')),
        int(config.get('extract_position', 'offset')))
    
    # Since Flurry returns events in reverse chronological order,
    # it is difficult to download events in a streaming fashion
    # from the same day. Therefore only download up to the previous
    # day's events.
    cur_date = date(year, month, day)
    if cur_date >= date.today():
        log.write('  All events extracted up to yesterday.\r\n')
        break
    
    if not did_login:
        conn = FlurryConnection(
            config.get('auth', 'email'),
            config.get('auth', 'password'),
            int(config.get('auth', 'project_id')))
        conn.login()
        did_login = True
    
    try:
        log.write('Downloading: %04d-%02d-%02d @ %d\r\n' % (year, month, day, offset))
        flurry_csv_stream = conn.download_log(year, month, day, offset)
    except RateLimitedError:
        if rate_limited_on_last_request:
            # Abort temporarily
            log.write('  Rate limited twice. Giving up.\r\n')
            break
        
        delay = float(config.get('rate_limiting', 'delay_per_overlimit'))
        log.write('  Rate limited. Retrying in %s seconds(s).\r\n' % delay)
        sleep(delay)
        
        conn.login()
        
        rate_limited_on_last_request = True
        continue
    else:
        rate_limited_on_last_request = False
    
    try:
        flurry_csv = csv.reader(flurry_csv_stream)
        
        col_names = flurry_csv.next()   # ignore column headers
        col_names = [col.strip() for col in col_names]  # strip whitespace
        expected_col_names = [
            'Timestamp', 'Session Index', 'Event', 'Description', 'Version',
            'Platform', 'Device', 'User ID', 'Params']
        assert col_names == expected_col_names
        
        cur_session_id = int(config.get('extract_position', 'session'))
        num_sessions_read = 0
        for row in flurry_csv:
            row = [col.strip() for col in row]  # strip whitespace
            
            # Pull apart the row
            (timestamp, session_index, event, description, version,
                platform, device, user_id, params) = row
            
            if session_index == '1':
                cur_session_id += 1
                num_sessions_read += 1
            
            # Output the original row data
            for i in xrange(len(col_names)):
                (k, v) = (col_names[i], row[i])
                output.write('%s=%s ' % (quote_k(k), quote_v(v)))
            
            # Append generated fields
            output.write('%s=%s ' % (quote_k('Session'), quote_v(str(cur_session_id))))
            
            # Break out the event parameters and output them individually
            for (k, v) in parse_params(params):
                k = '%s__%s' % (event, k)
                output.write('%s=%s ' % (quote_k(k), quote_v(v)))
            
            output.write('\r\n')
        
        output.flush()
        
        config.set('extract_position', 'session', str(cur_session_id))
        
        # Calculate next extraction offset
        if num_sessions_read > 0:
            # Potentially more sessions on the same day
            
            cur_offset = int(config.get('extract_position', 'offset'))
            next_offset = cur_offset + num_sessions_read
            
            config.set('extract_position', 'offset', str(next_offset))
            config_flush()
        else:
            # All events on the current day have been read
            
            cur_date = date(
                int(config.get('extract_position', 'year')),
                int(config.get('extract_position', 'month')),
                int(config.get('extract_position', 'day')))
            
            # TODO: Make this test less brittle.
            #       As is, events near midnight are likely to be lost,
            #       particularly if Splunk's and Flurry's clocks are out of sync.
            if cur_date < date.today():
                next_date = cur_date + timedelta(days=1)
                
                config.set('extract_position', 'year', str(next_date.year))
                config.set('extract_position', 'month', str(next_date.month))
                config.set('extract_position', 'day', str(next_date.day))
                config.set('extract_position', 'offset', str(0))
                config_flush()
            else:
                # No more events to extract
                # Must wait for more events to be logged
                log.write('  All events extracted.\r\n')
                break
    finally:
        flurry_csv_stream.close()
    
    # Delay between requests to avoid flooding Flurry
    sleep(float(config.get('rate_limiting', 'delay_per_request')))