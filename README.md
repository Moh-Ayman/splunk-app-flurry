This app provides a scripted input for [Splunk](http://www.splunk.com/) that automatically extracts event logs from [Flurry](http://www.flurry.com/). It is tested on Splunk 4.3.2.

This input permits the use of Splunk's advanced data analysis capabilities on Flurry data. This is particularly useful if your application logs custom events and you want to perform custom analyses on them.


Installation
============

* Install the app by copying the `flurry` directory to `$SPLUNK_HOME/etc/apps/flurry`.

* Fill in the appropriate configuration parameters in `$SPLUNK_HOME/etc/apps/flurry/local/extract.conf`:

  * `auth/{email,password}`: The credentials to login to the Flurry dashboard.
  * `auth/project_id`: Obtain this by logging in to the Flurry dashboard, clicking the name of the application you wish to monitor, and examining the dashboard's URL. It should look something like: https://dev.flurry.com/customDashboard.do?<b>projectID=<u>12345</u></b>&dashboardId=22
  * `rate_limiting/*`: Generally these parameters can be left alone.
  * `extract_position/{year,month,day}`: Set this to the earliest date containing events you wish to download.
  * `extract_position/offset`: Set this to 0.
  * `extract_position/session`: Set this to 0. This is used to generate an ID for each downloaded session.

* Enable the scripted input `$SPLUNK_HOME/etc/apps/flurry/local/extract.conf`.

* Wait 20 seconds or so for the new scripted input to extract the first couple of events.

* Run a test search `index=flurry` to see the events.

  * If you don't see any events, open the log `$SPLUNK_HOME/var/log/splunk/splunkd.log` and look for errors issued by ExecProcessor related to the `$SPLUNK_HOME/etc/apps/flurry/bin/extract.py` script. Most likely, the configured authentication credentials or the project ID was incorrect.


Example Searches
================

The following searches are installed by default:

* **Activity by Time of Day**:
  `sourcetype="flurry" | eval hour=strftime(_time, "%H") | stats count by hour | sort +hour`

* **Activity by Day of Week**:
  `sourcetype="flurry" | eval weekday=strftime(_time, "%w") | stats count by weekday | sort +weekday`

* **Top Users**:
  `sourcetype="flurry" Session_Index=1 | stats count by User_ID | sort -count`

If you log location information in events, you can use, in combination with the [Google Maps](http://splunk-base.splunk.com/apps/22365/google-maps) add-on:

* **Activity by Location**:
  `sourcetype=flurry EVENT_NAME__UserLocation=* | eval _geo=EVENT_NAME__UserLocation`

If you log OS information in events, you can use:

* **Activity by OS Version**:
  `sourcetype=flurry EVENT_NAME__SystemVersion=* | stats count by EVENT_NAME__SystemVersion | sort +EVENT_NAME__SystemVersion`
