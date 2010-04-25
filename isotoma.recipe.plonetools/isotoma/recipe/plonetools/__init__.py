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

            self.zeo_script = os.path.join(self.bin_directory, zeo_script)

    def is_zeo_started(self):
        # Is there a PID file?
        pid_file = self.options["zeo-pid-file"]
        if not os.path.exists(pid_file):
            return False

        pid = open(pid_file).read().strip()
        if not pid.isdigit():
            # There is a PID file but its broken
            return False

        pid = int(pid)

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
        options = self.options
        # XXX is this needed?
        self.installed.append(options['location'])
        if self.enabled:

            if not self.is_zeo_started() and self.zeoserver:
                zeo_start = "%s start" % self.zeo_script
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
                    zeo_stop = "%s stop" % self.zeo_script
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
        if o('site-replace', '') in TRUISMS:
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


class OptionsProxy(object):

    """
    An object that wraps a Buildout config and makes it more pythonic

    It means that we have real numbers, real bools, real lists and dicts...
    """

    def __init__(self, dict, blocked=None):
        self.dict = dict
        self.blocked = blocked or []

    def __getitem__(self, key):
        if not key in self.dict:
            raise KeyError("Key '%s' not found" % key)
        val = self.dict['key'].strip()
        if val.isdigit():
            return int(val)
        elif val.lower() == "true":
            return True
        elif val.lower() == "false":
            return False
        elif val.startswith("{") or val.startswith("["):
            return json.loads(val)
        else:
            return val

    def iteritems(self):
        for key in self.dict.iterkeys():
            yield key, self[key]


class Properties(Recipe):

    """
    This recipe writes all properties set on it into a .cfg in its part directory.
    It then runs a script to process this file and insert them into a plonesite as
    portal properties.
    """

    BLOCKED = ['recipe', 'script', 'instance', 'zeoserver', 'zeo-pid-file', 'location', 'site-id']

    def get_command(self):
        location = os.path.join(self.buildout['buildout']['parts-directory'], self.name)
        if not os.path.isdir(location):
            os.makedirs(location)
        location = os.path.join(location, "properties.cfg")

        args = {}
        for key, value in self.options.iteritems():
            if key.startswith("_") or key in self.BLOCKED:
                continue
            args[key] = value
        cfg = json.dumps(args)

        open(location, "w").write(cfg)
        self.installed.append(location)

        return "%(scriptname)s %(args)s" % {
            "scriptname": self.get_internal_script("setproperties.py"),
            "args": "--site-id=%s --properties=%s" % (self.options['site-id'], location)
            }


class Script(Recipe):

    """
    The script recipe takes a 'script' parameter: this is the script it runs

    Every other parameter is passed to the script in the form --key=val
    """

    BLOCKED = ['recipe', 'script', 'instance', 'zeoserver', 'zeo-pid-file', 'location']

    def get_command(self):
        args = []
        for key, value in self.options.iteritems():
            if key.startswith("_") or key in self.BLOCKED:
                continue
            if isinstance(value, list):
                for v in value:
                    args.append("--%s=%s" % (key, value))
            args.append("--%s=%s" % (key, value))

        return "%(scriptname)s %(args)s" % {
            "scriptname": self.options['script'],
            "args": " ".join(args)
            }

