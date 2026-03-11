# venus.Bluetti Monitor v1.0.0
Service to integrate a bluetti power station  into cerbos gui

The script has been developed with my current RV setup in mind.

The Python script create a virtual `com.victronenergy.battery` and push the values readed from `bluetti-read` script

you need to install via pip the `bluetti-bt-lib` 

### Configuration

* #### Manual
    see `config.ini` and amend for your needs.
    - `mac`: bluetooth mac address
    - `type`: bluetti device
    - `serial`: device serial 
    - `interval`: interval to query the bluetti
    - `standbycurrent`: current auto consumed by bluetti
    - `batterycapacity`: battery capacity in wh
    - `debug`: set log level to debug

### Installation
* #### prerequisites

    1. install pip and bluetti-bt-lib on venus os:
        - `opkg update`
        - `opkg install python3-pip`
        - `pip3 install bluetti-bt-lib`
    2. get the bluetti mac
        - `bluetti-scan`
* #### SetupHelper
    1. install [SetupHelper](https://github.com/kwindrem/SetupHelper)
    2. enter `Package Mager` in Settings
    3. Enter `Inactive Packages`
    4. on `new` enter the following:
        - `package name` -> `BluettiMonitor`
        - `GitHub user` -> `mebitek`
        - `GitHub branch or tag` -> `master`
    5. go to `Active packages` and click on `BluettiMonitor`
        - click on `download` -> `proceed`
        - click on `install` -> `proceed`

### Debugging
You can turn debug off on `config.ini` -> `debug=false`

The log you find in /var/log/BluettiMonitor

`tail -f -n 200 /data/log/BluettiMonitor/current`

You can check the status of the service with svstat:

`svstat /service/BluettiMonitor`

It will show something like this:

`/service/ChargerBluettiMonitorHelper: up (pid 10078) 325 seconds`

If the number of seconds is always 0 or 1 or any other small number, it means that the service crashes and gets restarted all the time.

When you think that the script crashes, start it directly from the command line:

`python /data/BluettiMonitor/BluettiMonitor.py`

and see if it throws any error messages.

If the script stops with the message

`dbus.exceptions.NameExistsException: Bus name already exists: com.victronenergy.grid"`

it means that the service is still running or another service is using that bus name.


### Hardware

tested with Bluetti EB3A