# This file is originally taken from Buildbot software.  
# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyrigth beg0 <beg0@free.fr>
# Copyright Buildbot Team Members

from __future__ import with_statement


# Based on the work of Dave Peticolas for the P4poll
# Changed to svn (using xml.dom.minidom) by Niklaus Giger
# Hacked beyond recognition by Brian Warner

import sys, os, subprocess, time
import xml.dom.minidom, urllib
import pynotify

class SVNInfo(object):
    url = ''
    user = None
    passwd = None
    histmax = 100
    svnbin = 'svn'
    project = ''
    cachepath = None
    split_file = None
    last_change = None

# these split_file_* functions are available for use as values to the
# split_file= argument.
def split_file_alwaystrunk(path):
    return dict(path=path)

def split_file_branches(path):
    # turn "trunk/subdir/file.c" into (None, "subdir/file.c")
    # and "trunk/subdir/" into (None, "subdir/")
    # and "trunk/" into (None, "")
    # and "branches/1.5.x/subdir/file.c" into ("branches/1.5.x", "subdir/file.c")
    # and "branches/1.5.x/subdir/" into ("branches/1.5.x", "subdir/")
    # and "branches/1.5.x/" into ("branches/1.5.x", "")
    pieces = path.split('/')
    if len(pieces) > 1 and pieces[0] == 'trunk':
        return (None, '/'.join(pieces[1:]))
    elif len(pieces) > 2 and pieces[0] == 'branches':
        return ('/'.join(pieces[0:2]), '/'.join(pieces[2:]))
    else:
        return None

def split_file_projects_branches(path):
    # turn projectname/trunk/subdir/file.c into dict(project=projectname, branch=trunk, path=subdir/file.c)
    if not "/" in path:
        return None
    project, path = path.split("/", 1)
    f = split_file_branches(path)
    if f:
        info = dict(project=project, path=f[1])
        if f[0]:
            info['branch'] = f[0]
        return info
    return f

def log_msg(msg):
	sys.stderr.writelines(msg + "\n")

def xml_get_text(element, tag_name):
    try:
        child_nodes = element.getElementsByTagName(tag_name)[0].childNodes
        text = "".join([t.data for t in child_nodes])
    except:
        text = "<unknown>"
    return text

def transform_path(path, prefix, split_file):
        if not path.startswith(prefix):
            log_msg("SVNPoller: ignoring path '%s' which doesn't"
                    "start with prefix '%s'" % (path, prefix))
            return
        relative_path = path[len(prefix):]
        if relative_path.startswith("/"):
            relative_path = relative_path[1:]
        where = split_file(relative_path)
        # 'where' is either None, (branch, final_path) or a dict
        if not where:
            return
        if isinstance(where, tuple):
            where = dict(branch=where[0], path=where[1])
        return where

def getSvnOutput(svn_data, cmd, extra_args = None):
        svn_args = [svn_data.svnbin, cmd, "--xml", "--non-interactive"]
        if svn_data.user:
            svn_args.append("--username=%s" % svn_data.user)
        if svn_data.passwd:
            svn_args.append("--password=%s" % svn_data.passwd)
        if extra_args:
            svn_args.extend(extra_args)
	svn_args.extend([svn_data.url])
        return subprocess.check_output(svn_args)

def determine_prefix(svnurl, output):
        try:
            doc = xml.dom.minidom.parseString(output)
        except xml.parsers.expat.ExpatError:
            log_msg("SVNPoller: determine_prefix: ExpatError in '%s'"
                    % output)
            raise
        rootnodes = doc.getElementsByTagName("root")
        if not rootnodes:
            # this happens if the URL we gave was already the root. In this
            # case, our prefix is empty.
            return ""
        rootnode = rootnodes[0]
        root = "".join([c.data for c in rootnode.childNodes])
        # root will be a unicode string
        if not svnurl.startswith(root):
            log_msg("svnurl='%s' doesn't start with <root>='%s'" % (svnurl, root))
            raise RuntimeError("Can't handle redirected svn connections!? "
                    "This shouldn't happen.")
        prefix = svnurl[len(root):]
        if prefix.startswith("/"):
            prefix = prefix[1:]
        log_msg("SVNPoller: svnurl=%s, root=%s, so prefix=%s" %
                (svnurl, root, prefix))
        return prefix

def pynotify_callback_function(notification=None, action=None, data=None):
       print "It worked!"

def submit_changes(changes):
        for chdict in changes:
            log_msg("got change rev %s  from author %s" % (chdict['revision'],chdict['author']))

            files = chdict['files']
            title = "SVN Change rev %(revision)s - %(author)s" % chdict
            msg  = ""
            for f in files[:2]:
		msg += " - " + f + "\n"
            if(len(files) == 3):
		msg += " - " + files[2] + "\n"
            elif(len(files) > 3):
                msg += "   ... (%s more files)\n" % str(len(files) - 2)

            msg += "\n"
            msg += chdict['comments']

            #n = pynotify.Notification("SVN Change rev %s" % chdict['revision'], "r%s - %s\n%s\n\n%s" % ( chdict['revision'], chdict['author'], "\n".join(chdict['files']), chdict['comments'] ))
            n = pynotify.Notification(title, msg)
            #n.set_urgency(pynotify.URGENCY_NORMAL)
            #n.set_timeout(pynotify.EXPIRES_NEVER)
            #n.add_action("clicked","Button text", pynotify_callback_function, None)
            n.show()


def create_changes(svn_data, new_logentries):
        changes = []

        for el in new_logentries:
            revision = str(el.getAttribute("revision"))

            log_msg("Adding change revision %s" % revision)
            author   = xml_get_text(el, "author")
            comments = xml_get_text(el, "msg")
            # there is a "date" field, but it provides localtime in the
            # repository's timezone, whereas we care about buildmaster's
            # localtime (since this will get used to position the boxes on
            # the Waterfall display, etc). So ignore the date field, and
            # addChange will fill in with the current time
            branches = {}
            try:
                pathlist = el.getElementsByTagName("paths")[0]
            except IndexError: # weird, we got an empty revision
                log_msg("ignoring commit with no paths")
                continue

            for p in pathlist.getElementsByTagName("path"):
                kind = p.getAttribute("kind")
                action = p.getAttribute("action")
                path = "".join([t.data for t in p.childNodes])
                # the rest of buildbot is certainly not yet ready to handle
                # unicode filenames, because they get put in RemoteCommands
                # which get sent via PB to the buildslave, and PB doesn't
                # handle unicode.
                path = path.encode("ascii")
                if path.startswith("/"):
                    path = path[1:]
                if kind == "dir" and not path.endswith("/"):
                    path += "/"
                where = transform_path(path, svn_data.prefix, svn_data.split_file)

                if where == None:
			log_msg("ignore file on " + path)

                # if 'where' is None, the file was outside any project that
                # we care about and we should ignore it
                if where:
                    branch = where.get("branch", None)
                    filename = where["path"]
                    if not branch in branches:
                        branches[branch] = { 'files': [], 'number_of_directories': 0}
                    if filename == "":
                        # root directory of branch
                        branches[branch]['files'].append(filename)
                        branches[branch]['number_of_directories'] += 1
                    elif filename.endswith("/"):
                        # subdirectory of branch
                        branches[branch]['files'].append(filename[:-1])
                        branches[branch]['number_of_directories'] += 1
                    else:
                        branches[branch]['files'].append(filename)

                    if "action" not in branches[branch]:
                        branches[branch]['action'] = action

                    for key in ("repository", "project", "codebase"):
                        if key in where:
                            branches[branch][key] = where[key]

            for branch in branches.keys():
                action = branches[branch]['action']
                files  = branches[branch]['files']

                number_of_directories_changed = branches[branch]['number_of_directories']
                number_of_files_changed = len(files)

                if action == u'D' and number_of_directories_changed == 1 and number_of_files_changed == 1 and files[0] == '':
                    log_msg("Ignoring deletion of branch '%s'" % branch)
                else:
                    chdict = dict(
                            author=author,
                            files=files,
                            comments=comments,
                            revision=revision,
                            branch=branch,
                            repository=branches[branch].get('repository', svn_data.url),
                            project=branches[branch].get('project', svn_data.project),
                            codebase=branches[branch].get('codebase', None))
                    changes.append(chdict)

        return changes

def get_new_logentries(svn_data, logentries):
        old_last_change = svn_data.last_change

        # given a list of logentries, calculate new_last_change, and
        # new_logentries, where new_logentries contains only the ones after
        # last_change

        new_last_change = None
        new_logentries = []
        if logentries:
            new_last_change = int(logentries[0].getAttribute("revision"))
	    log_msg("got rev " + str(new_last_change))

            if svn_data.last_change is None:
                # if this is the first time we've been run, ignore any changes
                # that occurred before now. This prevents a build at every
                # startup.
                log_msg('SVNPoller: starting at change %s' % new_last_change)
            elif svn_data.last_change == new_last_change:
                # an unmodified repository will hit this case
                log_msg('SVNPoller: no changes')
            else:
                for el in logentries:
                    if svn_data.last_change == int(el.getAttribute("revision")):
                        break
                    new_logentries.append(el)
                new_logentries.reverse() # return oldest first

        svn_data.last_change = new_last_change
        log_msg('SVNPoller: get_new_logentries %s .. %s' %
                (old_last_change, new_last_change))
        return new_logentries


def main():
    compare_attrs = ["svnurl", "split_file",
                     "svnuser", "svnpasswd", "project",
                     "pollInterval", "histmax",
                     "svnbin", "cachepath"]

    pynotify.init( "SVNPoller" )

    pollInterval = 10*60
    project = ''

    #TODO: better option handling
    if len(sys.argv) != 2:
	print "Usage: %s <svn_url>\n" % sys.argv[0]
	sys.exit(255)

    svnurl = sys.argv[1]

    svn_data = SVNInfo()
    svn_data.user = None
    svn_data.passwd = None
    svn_data.last_change = None
    svn_data.cachepath="/home/cca/.svnpoller"
    svn_data.prefix = None
    svn_data.histmax = 100
    #svn_data.split_file = split_file_projects_branches
    svn_data.split_file = split_file_alwaystrunk

    if svnurl.endswith("/"):
        svnurl = svnurl[:-1] # strip the trailing slash

    svn_data.url = svnurl
    if svn_data.cachepath and os.path.exists(svn_data.cachepath):
        try:
            with open(svn_data.cachepath, "r") as f:
                svn_data.last_change = int(f.read().strip())
                log_msg("SVNPoller: Polling %s setting last_change to %s" % (svn_data.url, svn_data.last_change))
            # try writing it, too
            with open(svn_data.cachepath, "w") as f:
                f.write(str(svn_data.last_change))
        except:
            svn_data.cachepath = None
            log_msg(("SVNPoller: Polling %s cache file corrupt or unwriteable; " +
                    "skipping and not using") % svn_data.url)
            sys.exit(255)

    def poll():
        # Our return value is only used for unit testing.

        # we need to figure out the repository root, so we can figure out
        # repository-relative pathnames later. Each SVNURL is in the form
        # (ROOT)/(PROJECT)/(BRANCH)/(FILEPATH), where (ROOT) is something
        # like svn://svn.twistedmatrix.com/svn/Twisted (i.e. there is a
        # physical repository at /svn/Twisted on that host), (PROJECT) is
        # something like Projects/Twisted (i.e. within the repository's
        # internal namespace, everything under Projects/Twisted/ has
        # something to do with Twisted, but these directory names do not
        # actually appear on the repository host), (BRANCH) is something like
        # "trunk" or "branches/2.0.x", and (FILEPATH) is a tree-relative
        # filename like "twisted/internet/defer.py".

        # our svnurl attribute contains (ROOT)/(PROJECT) combined
        # together in a way that we can't separate without svn's help. If the
        # user is not using the split_file= argument, then svnurl might
        # be (ROOT)/(PROJECT)/(BRANCH) . In any case, the filenames we will
        # get back from 'svn log' will be of the form
        # (PROJECT)/(BRANCH)/(FILEPATH), but we want to be able to remove
        # that (PROJECT) prefix from them. To do this without requiring the
        # user to tell us how svnurl is split into ROOT and PROJECT, we do an
        # 'svn info --xml' command at startup. This command will include a
        # <root> element that tells us ROOT. We then strip this prefix from
        # svnurl to determine PROJECT, and then later we strip the
        # PROJECT prefix from the filenames reported by 'svn log --xml' to
        # get a (BRANCH)/(FILEPATH) that can be passed to split_file() to
        # turn into separate BRANCH and FILEPATH values.

        # whew.

        if project:
            log_msg("SVNPoller: polling " + project)
        else:
            log_msg("SVNPoller: polling")

        try:
            svn_info_prefix = getSvnOutput(svn_data, "info")
            svn_data.prefix = determine_prefix(svn_data.url, svn_info_prefix)
	    logs_output = getSvnOutput(svn_data, "log",["-v", "--limit=%d" % (svn_data.histmax)])
            logentries = parse_logs(logs_output)
            new_logentries = get_new_logentries(svn_data, logentries)
            changes = create_changes(svn_data, new_logentries)
            submit_changes(changes)
            write_cache()
            log_msg("SVNPoller: finished polling %s" % svn_data.url)
        except Exception, e:
            log_msg("Error while pollinig %s: %s " % (svn_data.url, e.message))


    def parse_logs(output):
        # parse the XML output, return a list of <logentry> nodes
        try:
            doc = xml.dom.minidom.parseString(output)
        except xml.parsers.expat.ExpatError:
            log_msg("SVNPoller: SVNPoller.parse_logs: ExpatError in '%s'" % output)
            raise
        logentries = doc.getElementsByTagName("logentry")
        return logentries


    def write_cache():
        if svn_data.cachepath:
            with open(svn_data.cachepath, "w") as f:
                f.write(str(svn_data.last_change))

    while True:
        poll()
	time.sleep(pollInterval)


main()
