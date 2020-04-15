# Analytics Milter

This milter adds (Matomo)[https://matomo.org/] tracking parameters to e-mails
sent to specific e-mail addresses. This makes sense if you are running a Mailman
mailing list as an announce-only mailing list.

It wouldn't be hard to modify for Google Analytics tracking. In fact, since
Matomo can be configured to use Google parameters (`utm_content`, `utm_campaign`,
etc) that should *probably* be the default.

Tested with a Postfix mail server.

## Installation Instructions

These instructions are for a RHEL or CentOS system, as that's what I was working
with at the time. In particular steps 5 and 6 are likely to be different on your
system.

0. Modify the configuration portion of the script.
1. `adduser analyticsmilter`, `addgroup analyticsmilter`
2. `cp analyticsmilter.py /home/analyticsmilter/analyticsmilter.py`
3. `chown analyticsmilter:analyticsmilter /home/analyticsmilter/analyticsmilter.py`
4. Test by running: `sudo -u analyticsmilter /usr/bin/python /home/analyticsmilter/analyticsmilter.py`

If you send an e-mail to one of the e-mails specified in Step 1, you should be
able to see the milter working in real-time!

5. `cp analyticsmilter.service /usr/lib/systemd/system/analyticsmilter.service`
6. `systemctl enable analyticsmilter`