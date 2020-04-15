#!/usr/bin/python3
"Pymilter-based milter that adds Piwik / Matomo tracking parameters to links found in e-mails."

from time import strftime
import urllib
import tempfile
import email
import re
import io
import os
import sys

import Milter

# Configuration

# List of email addresses for which incoming mail should have tracking added:
TRACKED_EMAILS = ('mailinglist1@domain.com', 'mailinglist2@domain.com')
# Absolute URL to piwik.php script, used to track email opening:
PIWIK_IMAGE_URL = "https://domain.com/piwik/piwik.php?idsite=1"
# Socket name (will be used by Postfix to communicate with milter)
#SOCKETNAME = os.getenv("HOME") + "/analyticsmiltersock"
SOCKETNAME = 'inet:12085@127.0.0.1'

# End of Configuration


class AnalyticsMilter(Milter.Milter):
    "Milter that adds Matomo tracking to e-mails."

    def log(self, *msg):
        "Output messages to STDOUT"
        print("%s [%d]" % (strftime('%Y%b%d %H:%M:%S'), self.milter_id))
        for i in msg:
            print(i + "\n")

    def __init__(self):
        self.tempname = None
        self.mailfrom = None
        self.buffer = None
        self.bodysize = 0
        self.milter_id = Milter.uniqueID()

    # multiple messages can be received on a single connection
    # envfrom (MAIL FROM in the SMTP protocol) seems to mark the start
    # of each message.
    @Milter.noreply
    def envfrom(self, f, *str):
        "start of MAIL transaction"
        self.log("mail from", f, str)
        self.buffer = io.StringIO()
        self.tempname = None
        self.mailfrom = f
        self.bodysize = 0
        return Milter.CONTINUE  # pylint:disable=E1101

    def envrcpt(self, to, *str):
        "Check if the To: address is one of the tracked e-mail addresses."
        if any(e in to for e in TRACKED_EMAILS):
            self.log('Found one! To:', to, str)
            return Milter.CONTINUE  # pylint:disable=E1101
        return Milter.ACCEPT  # pylint:disable=E1101

    def header(self, name, val):
        "Record e-mail header in buffer"
        if self.buffer:
            self.buffer.write("%s: %s\n" % (name, val))  # add header to buffer
        return Milter.CONTINUE  # pylint:disable=E1101

    def eoh(self):
        "Copy headers to a temp file so buffer can be used for body"
        if not self.buffer: # not seen by envfrom
            return Milter.TEMPFAIL  # pylint:disable=E1101
        self.buffer.write("\n")
        self.buffer.seek(0)
        # copy headers to a temp file for scanning the body
        headers = self.buffer.getvalue()
        self.buffer.close()
        self.tempname = fname = tempfile.mktemp(".defang")
        self.buffer = open(fname, "w+b")
        self.buffer.write(headers)  # IOError (e.g. disk full) causes TEMPFAIL
        return Milter.CONTINUE  # pylint:disable=E1101

    def body(self, chunk):    # copy body to temp file
        "Copy body to a tempfile"
        if self.buffer:
            self.buffer.write(chunk)  # IOError causes TEMPFAIL in milter
            self.bodysize += len(chunk)
        return Milter.CONTINUE  # pylint:disable=E1101

    def _header_change(self, msg, name, value):
        if value:  # add header
            self.addheader(name, value)
        else:  # delete all headers with name
            headers = msg.getheaders(name)
            cnt = len(headers)
            for i in range(cnt, 0, -1):
                self.chgheader(name, i-1, '')

    def _fix_content(self, content):
        content = self._add_tracking_to_links(content)
        content = self._add_tracking_image(content)
        return content

    def _add_tracking_to_links(self, content):
        self.log("Adding piwik tracking to links")
        relink = re.compile(
            r'<(a[^>]+href)="([^"]+)"([^>]*)>(.*?)</(a)>', re.S | re.I)
        restrip = re.compile(r'<([^>]+)>', re.S | re.I)
        respace = re.compile(r'[\s&]+', re.S)
        img_number = 1
        for match in relink.finditer(content):
            res = match.group(1, 2, 3, 4, 5)
            keyword = match.group(4)
            if keyword.find('<img') >= 0:
                keyword = "image %d" % img_number
                img_number += 1
            else:
                # remove tags from keyword
                keyword = restrip.sub('', keyword)
                keyword = respace.sub(' ', keyword)
            # url encode keyword
            keyword = urllib.parse.quote_plus(keyword)
            # substitute into content
            str1 = '<%s="%s"%s>%s</%s>' % res[0:5]
            self.log(str1)
            str2 = '<%s="%s#pk_campaign=newsletter%s&amp;pk_kwd=%s"%s>%s</%s>' % (
                res[0], res[1], strftime('%Y-%b-%d'), keyword, res[2], res[3], res[4])
            self.log(str2)
            content = content.replace(str1, str2)
        return content

    def _add_tracking_image(self, content):
        self.log("Adding tracking image to end of e-mail body")
        tempstr = \
            '<img src="%s&amp;rec=1&amp;bots=1&amp;action_name=newsletter-open' + \
            '&amp;e_c=newsletter&amp;e_a=open&amp;e_n=newsletter-%s" height="1" width="1">'
        content += tempstr % (PIWIK_IMAGE_URL, strftime('%Y-%b-%d'))
        return content

    def _modify_part(self, part):
        content = part.get_payload(decode=True)
        content = self._fix_content(content)
        self.log("Encoding part")
        part.set_type('text/html')
        part.set_payload(content)
        del part["content-transfer-encoding"]
        email.Encoders.encode_quopri(part)
        return part

    def _find_html_part(self, part):
        parttype = part.get_content_type().lower()
        self.log("Part type:", parttype)
        if parttype == 'text/html':
            self.log("Modifying part")
            part = self._modify_part(part)
            return True
        if parttype.startswith('multipart'):
            self.log("Iterating part")
            return self._add_tracking(part)
        return False

    def _add_tracking(self, msg):
        if msg.is_multipart():
            parts = msg.get_payload()
            for part in parts:
                # return true if we modified the part
                if self._find_html_part(part):
                    return True
        return self._find_html_part(msg)

    def eom(self):
        "Attempt to replace message body if message matched our critera"
        if not self.buffer:
            return Milter.ACCEPT  # pylint:disable=E1101
        self.buffer.seek(0)
        msg = email.message_from_file(self.buffer)
        # Remove all headers so we can work with just body
        msg.headerchange = self._header_change
        # Add tracking, if it doesn't work, then just let the e-mail through
        # In the case of tracking marketing e-mails, this is safer than blocking the e-mail.
        if not self._add_tracking(msg):
            self.log("No parts modified")
            return Milter.ACCEPT  # pylint:disable=E1101
        # If message is modified by _add_tracking:
        self.log("Temp file:", self.tempname)
        self.tempname = None  # prevent removal of original message copy
        # copy tracked message to a temp file
        out = tempfile.TemporaryFile()
        try:
            msg.dump(out)
            out.seek(0)
            #msg = rfc822.Message(out)
            # msg.rewindbody()
            while 1:
                buf = out.read(8192)
                if len(buf) == 0:
                    break
            self.replacebody(buf)  # feed modified message to sendmail
            # ACCEPT modified message
            return Milter.ACCEPT  # pylint:disable=E1101
        finally:
            out.close()
        return Milter.TEMPFAIL  # pylint:disable=E1101

    def close(self):
        "Print output and clean up"
        sys.stdout.flush()    # make log messages visible
        if self.tempname:
            os.remove(self.tempname)  # remove in case session aborted
        if self.buffer:
            self.buffer.close()
        return Milter.CONTINUE  # pylint:disable=E1101

    def abort(self):
        "Report if AnalyticsMilter is interrupted"
        self.log("abort after %d body chars" % self.bodysize)
        return Milter.CONTINUE  # pylint:disable=E1101


if __name__ == "__main__":
    Milter.factory = AnalyticsMilter
    print("""To use this with sendmail, add the following to sendmail.cf:

O InputMailFilters=analyticsmilter
Xanalyticsmilter,        S=local:%s

See the sendmail README for libmilter.

To use this with Postfix, add the following to main.cf:

smtpd_milters = local:%s $smtpd_milters

tracking milter startup""" % (SOCKETNAME, SOCKETNAME))
    sys.stdout.flush()
    Milter.runmilter("analyticsmilter", SOCKETNAME, 240)
    print("tracking milter shutdown")
