
# Milter to add Piwik tracking parameters to Mailman e-mails
# Not too hard to modify for Google Analytics tracking

# Installation instructions
# 1. adduser trackingmilter
# 2. cp trackingmilter.py /home/trackingmilter/trackingmilter.py
# 3. chown trackingmilter:trackingmilter /home/trackingmilter/trackingmilter.py
# 4. TEST: sudo -u trackingmilter /usr/bin/python /home/trackingmilter/trackingmilter.py
# 5. cp trackingmilter.service /usr/lib/systemd/system/trackingmilter.service
# 6. systemctl enable trackingmilter

# Configuration

# List of email addresses for which incoming mail should have tracking added:
TRACKED_EMAILS = ('mailinglist1@domain.com','mailinglist2@domain.com')
# Absolute URL to piwik.php script, used to track email opening:
PIWIK_IMAGE_URL = "https://domain.com/piwik/piwik.php?idsite=1"
# Socket name (will be used by Postfix to communicate with milter)
#SOCKETNAME = os.getenv("HOME") + "/trackingmiltersock"
SOCKETNAME = 'inet:12085@127.0.0.1'

# End of Configuration

import sys
import os
import StringIO
import rfc822
import re
import email
import mime
import Milter
import tempfile
import urllib
from time import strftime

class trackingMilter(Milter.Milter):
  "Milter that adds Piwik tracking to e-mails."

  def log(self,*msg):
    print "%s [%d]" % (strftime('%Y%b%d %H:%M:%S'),self.id),
    for i in msg: print i,
    print

  def __init__(self):
    self.tempname = None
    self.mailfrom = None
    self.fp = None
    self.bodysize = 0
    self.id = Milter.uniqueID()

  # multiple messages can be received on a single connection
  # envfrom (MAIL FROM in the SMTP protocol) seems to mark the start
  # of each message.
  @Milter.noreply
  def envfrom(self,f,*str):
    "start of MAIL transaction"
    self.log("mail from",f,str)
    self.fp = StringIO.StringIO()
    self.tempname = None
    self.mailfrom = f
    self.bodysize = 0
    return Milter.CONTINUE

  def envrcpt(self,to,*str):
    if any(e in to for e in TRACKED_EMAILS):
      self.log('Found one! To:',to,str)
      return Milter.CONTINUE
    return Milter.ACCEPT

  def header(self,name,val):
    if self.fp:
      self.fp.write("%s: %s\n" % (name,val))  # add header to buffer
    return Milter.CONTINUE

  def eoh(self):
    if not self.fp: return Milter.TEMPFAIL  # not seen by envfrom
    self.fp.write("\n")
    self.fp.seek(0)
    # copy headers to a temp file for scanning the body
    headers = self.fp.getvalue()
    self.fp.close()
    self.tempname = fname = tempfile.mktemp(".defang")
    self.fp = open(fname,"w+b")
    self.fp.write(headers)  # IOError (e.g. disk full) causes TEMPFAIL
    return Milter.CONTINUE

  def body(self,chunk):    # copy body to temp file
    if self.fp:
      self.fp.write(chunk)  # IOError causes TEMPFAIL in milter
      self.bodysize += len(chunk)
    return Milter.CONTINUE

  def _headerChange(self,msg,name,value):
    if value:  # add header
      self.addheader(name,value)
    else:  # delete all headers with name
      h = msg.getheaders(name)
      cnt = len(h)
      for i in range(cnt,0,-1):
        self.chgheader(name,i-1,'')

  def _fixContent(self,content):
    self.log("Adding piwik tracking to links")
    relink = re.compile(r'<(a[^>]+href)="([^"]+)"([^>]*)>(.*?)</(a)>', re.S|re.I)
    restrip = re.compile(r'<([^>]+)>', re.S|re.I)
    respace = re.compile(r'[\s&]+', re.S)
    x=1
    for match in relink.finditer(content):
      res = match.group(1,2,3,4,5)
      keyword = match.group(4)
      if keyword.find('<img') >= 0:
        keyword = "image %d" % x
        x+=1
      else:
        # remove tags from keyword
        keyword = restrip.sub('',keyword)
        keyword = respace.sub(' ',keyword)
      # url encode keyword
      keyword = urllib.quote_plus(keyword)
      # substitute into content
      str1 = '<%s="%s"%s>%s</%s>' % res[0:5]
      self.log(str1);
      str2 = '<%s="%s#pk_campaign=newsletter%s&amp;pk_kwd=%s"%s>%s</%s>' % (res[0], res[1], strftime('%Y-%b-%d'), keyword, res[2], res[3], res[4])
      self.log(str2);
      content = content.replace(str1, str2)
    self.log("Adding tracking image to links")
    content += '<img src="%s&amp;rec=1&amp;bots=1&amp;action_name=newsletter-open&amp;e_c=newsletter&amp;e_a=open&amp;e_n=newsletter-%s" height="1" width="1">' % (PIWIK_IMAGE_URL, strftime('%Y-%b-%d'))
    return content

  def _modifyPart(self,part):
    content = part.get_payload(decode=True)
    content = self._fixContent(content)
    self.log("Encoding part")
    part.set_type('text/html')
    part.set_payload(content)
    del part["content-transfer-encoding"]
    email.Encoders.encode_quopri(part)
    return part

  def _findHtmlPart(self,part):
    parttype = part.get_content_type().lower()
    self.log("Part type:",parttype)
    if parttype == 'text/html':
      self.log("Modifying part")
      part = self._modifyPart(part)
      return True
    elif parttype.startswith('multipart') :
      self.log("Iterating part")
      return self._addTracking(part)

  def _addTracking(self,msg):
    if msg.is_multipart():
      parts = msg.get_payload()
      for part in parts:
        # return true if we modified the part
        if self._findHtmlPart(part):
          return True
    else:
      return self._findHtmlPart(msg)
    self.log("Returning False")
    return False

  def eom(self):
    if not self.fp: return Milter.ACCEPT
    self.fp.seek(0)
    msg = mime.message_from_file(self.fp)
    msg.headerchange = self._headerChange # Remove all headers so we can work with just body
    # Add tracking, if it doesn't work, then just rubber-stamp the e-mail through
    if not self._addTracking(msg):
      self.log("No parts modified")
      return Milter.ACCEPT
    # If message is modified by addTracking:
    self.log("Temp file:",self.tempname)
    self.tempname = None  # prevent removal of original message copy
    # copy tracked message to a temp file
    out = tempfile.TemporaryFile()
    try:
      msg.dump(out)
      out.seek(0)
      msg = rfc822.Message(out)
      msg.rewindbody()
      while 1:
        buf = out.read(8192)
        if len(buf) == 0: break
        self.replacebody(buf)  # feed modified message to sendmail
      return Milter.ACCEPT  # ACCEPT modified message
    finally:
      out.close()
    return Milter.TEMPFAIL

  def close(self):
    sys.stdout.flush()    # make log messages visible
    if self.tempname:
      os.remove(self.tempname)  # remove in case session aborted
    if self.fp:
      self.fp.close()
    return Milter.CONTINUE

  def abort(self):
    self.log("abort after %d body chars" % self.bodysize)
    return Milter.CONTINUE

if __name__ == "__main__":
  Milter.factory = trackingMilter
  Milter.set_flags(Milter.CHGBODY + Milter.CHGHDRS + Milter.ADDHDRS)
  print """To use this with sendmail, add the following to sendmail.cf:

O InputMailFilters=trackingmilter
Xtrackingmilter,        S=local:%s

See the sendmail README for libmilter.

To use this with Postfix, add the following to main.cf:

smtpd_milters = local:%s $smtpd_milters

tracking milter startup""" % (SOCKETNAME, SOCKETNAME)
  sys.stdout.flush()
  Milter.runmilter("trackingmilter",SOCKETNAME,240)
  print "tracking milter shutdown"