# Tracking Milter

This milter adds (Matomo)[https://matomo.org/] tracking parameters to e-mails
originating from specific e-mail addresses. It wouldn't be hard to modify for
Google Analytics tracking.

Tested with a Postfix mail server.

## Installation Instructions

These instructions are for a RHEL or CentOS system, as that's what I was working
with at the time. In particular steps 5 and 6 are likely to be different on your
system.

1. `adduser trackingmilter`, `addgroup trackingmilter`
2. `cp trackingmilter.py /home/trackingmilter/trackingmilter.py`
3. `chown trackingmilter:trackingmilter /home/trackingmilter/trackingmilter.py`
4. Test: `sudo -u trackingmilter /usr/bin/python /home/trackingmilter/trackingmilter.py`
5. `cp trackingmilter.service /usr/lib/systemd/system/trackingmilter.service`
6. `systemctl enable trackingmilter`