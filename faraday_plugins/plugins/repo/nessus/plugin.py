#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
Faraday Penetration Test IDE
Copyright (C) 2013  Infobyte LLC (http://www.infobytesec.com/)
See the file 'doc/LICENSE' for the license information

'''
from __future__ import with_statement
import logging
from faraday.client.plugins import core
from faraday.client.model import api
import re
import os
import socket
import pprint
import sys
import dotnessus_v2

logger = logging.getLogger(__name__)

current_path = os.path.abspath(os.getcwd())

__author__ = "Francisco Amato"
__copyright__ = "Copyright (c) 2013, Infobyte LLC"
__credits__ = ["Francisco Amato"]
__license__ = ""
__version__ = "1.0.0"
__maintainer__ = "Francisco Amato"
__email__ = "famato@infobytesec.com"
__status__ = "Development"


class NessusParser(object):
    """
    The objective of this class is to parse an xml file generated by the nessus tool.

    TODO: Handle errors.
    TODO: Test nessus output version. Handle what happens if the parser doesn't support it.
    TODO: Test cases.

    @param nessus_filepath A proper simple report generated by nessus
    """

    def __init__(self, output):
        lists = output.split("\r\n")
        i = 0
        self.items = []
        if re.search("Could not reach", output) is not None:
            self.fail = True
            return

        for line in lists:
            if i > 8:
                item = {'link': line}
                self.items.append(item)
            i = i + 1


class NessusPlugin(core.PluginBase):
    """
    Example plugin to parse nessus output.
    """

    def __init__(self):
        core.PluginBase.__init__(self)
        self.id = "Nessus"
        self.name = "Nessus XML Output Plugin"
        self.plugin_version = "0.0.1"
        self.version = "5.2.4"
        self.framework_version = "1.0.1"
        self.options = None
        self._current_output = None
        self._current_path = None
        self._command_regex = re.compile(
            r'^(nessus|sudo nessus|\.\/nessus).*?')
        self.host = None
        self.port = None
        self.protocol = None
        self.fail = None

        global current_path
        self.output_path = os.path.join(self.data_path,
                                        "nessus_output-%s.txt" % self._rid)

    def canParseCommandString(self, current_input):
        if self._command_regex.match(current_input.strip()):
            return True
        else:
            return False

    def parseOutputString(self, output, debug=False):
        """
        This method will discard the output the shell sends, it will read it from
        the xml where it expects it to be present.

        NOTE: if 'debug' is true then it is being run from a test case and the
        output being sent is valid.
        """
        p = dotnessus_v2.Report()
        try:
            p.parse(output, from_string=True)
        except Exception as e:
            logger.error("Exception - %s", e)

        for t in p.targets:
            mac = ""
            host = ""
            ip = ""

            if t.get('mac-address'):
                mac = t.get('mac-address')
            if t.get('host-fqdn'):
                host = t.get('host-fqdn')
            if t.get('host-ip'):
                ip = t.get('host-ip')

            if not ip:
                if not t.get_ips():
                    continue
                ip = t.get_ips().pop()

            h_id = self.createAndAddHost(ip, t.get('operating-system'), hostnames=[host])

            if self._isIPV4(ip):
                i_id = self.createAndAddInterface(
                    h_id, ip, mac, ipv4_address=ip, hostname_resolution=[host])
            else:
                i_id = self.createAndAddInterface(
                    h_id, ip, mac, ipv6_address=ip, hostname_resolution=[host])

            srv = {}
            web = False
            for v in t.vulns:
                external_id = ""

                external_id = v.get('plugin_id')

                desc = ""
                desc += v.get('description').encode("ascii",
                                                    errors="backslashreplace") if v.get('description') else ""
                resolution = ""
                resolution = v.get('solution').encode(
                    "ascii", errors="backslashreplace") if v.get('solution') else ""

                data = "\nOutput: " + v.get('plugin_output').encode(
                    "ascii", errors="backslashreplace") if v.get('plugin_output') else ""

                ref = []
                if v.get('cve'):
                    cves = v.get('cve')
                    for cve in cves:
                        logger.debug('Appending %s', cve.encode("utf-8"))
                        ref.append(cve.encode("utf-8").strip())
                if v.get('bid'):
                    bids = v.get('bid')
                    for bid in bids:
                        logger.debug('Appending %s', bid.encode("utf-8"))
                        ref.append("BID-%s" % bid.encode("utf-8").strip() )
                if v.get('cvss_base_score'):
                    ref.append("CVSS: " + ", ".join(v.get('cvss_base_score')))
                if v.get('xref'):
                    ref.append(", ".join(v.get('xref')))
                if v.get('svc_name') == "general":
                    v_id = self.createAndAddVulnToHost(h_id, v.get('plugin_name'),
                                                       desc=desc, ref=ref, data=data, severity=v.get('severity'), resolution=resolution, external_id=external_id)
                else:

                    s_id = self.createAndAddServiceToInterface(h_id, i_id, v.get('svc_name'),
                                                               v.get(
                                                                   'protocol'),
                                                               ports=[
                                                                   str(v.get('port'))],
                                                               status="open")

                    web = True if re.search(
                        r'^(www|http)', v.get('svc_name')) else False
                    if srv.has_key(v.get('svc_name')) == False:
                        srv[v.get('svc_name')] = 1
                        if web:
                            n_id = self.createAndAddNoteToService(
                                h_id, s_id, "website", "")
                            n2_id = self.createAndAddNoteToNote(
                                h_id, s_id, n_id, host, "")

                    if web:
                        v_id = self.createAndAddVulnWebToService(h_id, s_id, v.get('plugin_name'),
                                                                 desc=desc, data=data, website=host, severity=v.get('severity'),
                                                                 resolution=resolution, ref=ref, external_id=external_id)
                    else:
                        v_id = self.createAndAddVulnToService(h_id, s_id, v.get('plugin_name'),
                                                              desc=desc, data=data, severity=v.get('severity'), resolution=resolution,
                                                              ref=ref, external_id=external_id)

    def _isIPV4(self, ip):
        if len(ip.split(".")) == 4:
            return True
        else:
            return False

    def processCommandString(self, username, current_path, command_string):
        return None

    def setHost(self):
        pass

    def resolve(self, host):
        try:
            return socket.gethostbyname(host)
        except:
            pass
        return host


def createPlugin():
    return NessusPlugin()

if __name__ == '__main__':
    parser = NessusPlugin()
    with open('/home/dnadares/report-collection/latest_reports/DNS_publicos_hlnn77.nessus', 'r') as report:
        parser.parseOutputString(report.read())
        for item in parser.items:
            if item.status == 'up':
                print item
