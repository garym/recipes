# -*- coding: utf-8 -*-
"""Recipe plonesite"""

import os
import sys
import subprocess
import pkg_resources
from zc.buildout import UserError
import simplejson as json

TRUISMS = [
    'yes',
    'y',
    'on',
    'true',
    'sure',
    'ok',
    '1',
]

def system(c):
    if os.system(c):
        raise SystemError("Failed", c)

class Recipe(object):
    """zc.buildout recipe"""

    def __init__(self, buildout, name, options):
        self.buildout, self.name, self.options = buildout, name, options
        options['location'] = os.path.join(
            buildout['buildout']['parts-directory'],
            self.name,
            )

        self.installed = []
        self.stop_zeo = False
        self.bin_directory = buildout['buildout']['bin-directory']

        # We can disable the starting of zope and zeo.  useful from the
        # command line:
        # $ bin/buildout -v plonesite:enabled=false
        self.enabled = options.get('enabled', 'true').lower() in TRUISMS

        # figure out if we need a zeo server started, and if it's on windows
        # this code was borrowed from plone.recipe.runscript
        is_win = sys.platform[:3].lower() == "win"
        # grab the 'instance' option and default to 'instance' if it does not exist
        instance = buildout[options.get('instance', 'instance')]
        instance_home = instance['location']
        instance_script = os.path.basename(instance_home)
        if is_win:
            instance_script = "%s.exe" % instance_script
        self.instance_script = instance_script

        self.zeoserver = options.get('zeoserver', False)
        if self.zeoserver:
            if is_win:
                zeo_script = 'zeoservice.exe'
            else:
                zeo_home = buildout[self.zeoserver]['location']
                zeo_script = os.path.basename(zeo_home)

            options.setdefault("zeo-script", os.path.join(self.bin_directory, zeo_script))
            options.setdefault("zeo-pid-file", os.path.join(buildout['buildout']['directory'], "var", "%s.pid" % self.zeoserver))

    def is_zeo_started(self):
        # Is there a PID file?
        pid_file = self.options["zeo-pid-file"]
        if not os.path.exists(pid_file):
            return False

        # Read PID file, make sure its an int
        pid = open(pid_file).read().strip()
        try:
            pid = int(pid)
        except:
            return False

        # Try kill() with signal 0
        # No exceptions means the zeoserver is running
        #  Special case: if we dont have permissions, give up
        try:
            os.kill(pid, 0)
            return True
        except OSError, e:
            if e.errno == 3:
                raise UserError("We don't have permission to check the status of that zeoserver")

        return False

    def install(self):
        """
        1. Run the before-install command if specified
        2. Start up the zeoserver if specified
        3. Run the script
        4. Stop the zeoserver if specified
        5. Run the after-install command if specified
        """

        # XXX is this needed?
        self.installed.append(self.options['location'])

        if self.enabled:

            if not self.is_zeo_started() and self.zeoserver:
                zeo_start = "%s start" % self.options["zeo-script"]
                subprocess.call(zeo_start.split())
                self.stop_zeo = True

            try:
                # work out what to run
                cmd = "%(bin-directory)s/%(instance-script)s run %(command)s" % {
                    "bin-directory": self.bin_directory,
                    "instance-script": self.instance_script,
                    "command": self.get_command()
                    }
                print cmd

                # run the script
                result = subprocess.call(cmd.split())
                if result > 0:
                    raise UserError("Plone script could not complete")
            finally:
                if self.stop_zeo:
                    zeo_stop = "%s stop" % self.options["zeo-script"]
                    subprocess.call(zeo_stop.split())

        return self.installed

    def get_internal_script(self, scriptname):
        return pkg_resources.resource_filename(__name__, scriptname)

    def update(self):
        """Updater"""
        self.install()


class Site(Recipe):

    def install(self):
        before_install = self.options.get("before-install", None)
        if before_install:
           system(before_install)

        super(Site, self).install()

        after_install = self.options.get("after-install", None)
        if after_install:
            system(after_install)

        return self.installed

    def get_command(self):
        o = self.options.get

        args = []
        args.append("--site-id=%s" % o("site-id", "Plone"))
        # only pass the site replace option if it's True
        if o('site-replace', '').lower() in TRUISMS:
            args.append("--site-replace")
        args.append("--admin-user=%s" % o("admin-user", "admin"))

        def createArgList(arg_name, arg_list):
            if arg_list:
                for arg in arg_list:
                    args.append("%s=%s" % (arg_name, arg))

        createArgList('--pre-extras', o("pre-extras", "").split())
        createArgList('--post-extras', o("post-extras", "").split())
        createArgList('--products-initial', o("products-initial", "").split())
        createArgList('--products', o("products", "").split())
        createArgList('--profiles-initial', o("profiles-initial", "").split())
        createArgList('--profiles', o("profiles", "").split())

        return "%(scriptname)s %(args)s" % {
            "scriptname": self.get_internal_script("plonesite.py"),
            "args": " ".join(args)
            }


class Properties(Recipe):

    """
    This recipe writes all properties set on it into a .cfg in its part directory.
    It then runs a script to process this file and insert them into a plonesite as
    portal properties.
    """

    def get_command(self):
        location = os.path.join(self.buildout['buildout']['parts-directory'], self.name)
        if not os.path.isdir(location):
            os.makedirs(location)
        location = os.path.join(location, "properties.cfg")

        open(location, "w").write(self.options.get("properties", "{}"))
        self.installed.append(location)

        return "%(scriptname)s %(args)s" % {
            "scriptname": self.get_internal_script("setproperties.py"),
            "args": "--site-id=%s --properties=%s" % (self.options['site-id'], location)
            }


class Script(Recipe):

    """
    The script recipe takes a 'command' parameter: this is what to tell the
    instance script to run
    """

    def get_command(self):
        return self.options["command"]


