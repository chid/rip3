__version__ = "0.4"

__all__ = ["CGIHTTPRequestHandler"]

import os
import sys
import urllib
import BaseHTTPServer
import SimpleHTTPServer
import select
import copy


class CGIHTTPRequestHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):

    """Complete HTTP server with GET, HEAD and POST commands.

    GET and HEAD also support running CGI scripts.

    The POST command is *only* implemented for CGI scripts.

    """

    # Determine platform specifics
    have_fork = hasattr(os, 'fork')
    have_popen2 = hasattr(os, 'popen2')
    have_popen3 = hasattr(os, 'popen3')

    # Make rfile unbuffered -- we need to read one line and then pass
    # the rest to a subprocess, so we can't use buffered input.
    rbufsize = 0

    def do_POST(self):
        """Serve a POST request.

        This is only implemented for CGI scripts.

        """

        if self.is_cgi():
            self.run_cgi()
        else:
            self.send_error(501, "Can only POST to CGI scripts")

    def send_head(self):
        """Version of send_head that support CGI scripts"""
        if self.is_cgi():
            return self.run_cgi()
        else:
            return SimpleHTTPServer.SimpleHTTPRequestHandler.send_head(self)

    def is_cgi(self):
        """Test whether self.path corresponds to a CGI script.

        Returns True and updates the cgi_info attribute to the tuple
        (dir, rest) if self.path requires running a CGI script.
        Returns False otherwise.

        If any exception is raised, the caller should assume that
        self.path was rejected as invalid and act accordingly.

        The default implementation tests whether the normalized url
        path begins with one of the strings in self.cgi_directories
        (and the next character is a '/' or the end of the string).
        """
        splitpath = _url_collapse_path_split(self.path)
        if splitpath[0] in self.cgi_directories:
            self.cgi_info = splitpath
            return True        
        i = self.path.rfind('?')
        rest = self.path
        if i >= 0:
            rest = rest[:i]
        if os.path.splitext(rest)[1][1:] in self.cgi_extensions:
            self.cgi_info = splitpath
            return True
        return False

    cgi_directories = ['/cgi-bin', '/htbin']
    cgi_extensions = ["cgi"]

    def is_executable(self, path):
        """Test whether argument path is an executable file."""
        return executable(path)

    def is_python(self, path):
        return True
        """Test whether argument path is a Python script."""
        head, tail = os.path.splitext(path)
        return tail.lower() in (".py", ".pyw")

    def run_cgi(self):
        """Execute a CGI script."""
        path = self.path
        dir, rest = self.cgi_info

        i = path.find('/', len(dir) + 1)
        while i >= 0:
            nextdir = path[:i]
            nextrest = path[i+1:]

            scriptdir = self.translate_path(nextdir)
            if os.path.isdir(scriptdir):
                dir, rest = nextdir, nextrest
                i = path.find('/', len(dir) + 1)
            else:
                break

        # find an explicit query string, if present.
        i = rest.rfind('?')
        if i >= 0:
            rest, query = rest[:i], rest[i+1:]
        else:
            query = ''

        # dissect the part after the directory name into a script name &
        # a possible additional path, to be stored in PATH_INFO.
        i = rest.find('/')
        print rest
        if i >= 0:
            script, rest = rest[:i], rest[i:]
        else:
            script, rest = rest, ''

        scriptname = dir + '/' + script
        scriptfile = self.translate_path(scriptname)
        if not os.path.exists(scriptfile):
            self.send_error(404, "No such CGI script (%r)" % scriptname)
            return
        if not os.path.isfile(scriptfile):
            self.send_error(403, "CGI script is not a plain file (%r)" %
                            scriptname)
            return
        ispy = self.is_python(scriptname)
        # print str(ispy) + "am i python?"
        if not ispy:
            if not (self.have_fork or self.have_popen2 or self.have_popen3):
                self.send_error(403, "CGI script is not a Python script (%r)" %
                                scriptname)
                return
            if not self.is_executable(scriptfile):
                self.send_error(403, "CGI script is not executable (%r)" %
                                scriptname)
                return

        # Reference: http://hoohoo.ncsa.uiuc.edu/cgi/env.html
        # XXX Much of the following could be prepared ahead of time!
        env = copy.deepcopy(os.environ)
        env['SERVER_SOFTWARE'] = self.version_string()
        env['SERVER_NAME'] = self.server.server_name
        env['GATEWAY_INTERFACE'] = 'CGI/1.1'
        env['SERVER_PROTOCOL'] = self.protocol_version
        env['SERVER_PORT'] = str(self.server.server_port)
        env['REQUEST_METHOD'] = self.command
        uqrest = urllib.unquote(rest)
        env['PATH_INFO'] = uqrest
        env['PATH_TRANSLATED'] = self.translate_path(uqrest)
        env['SCRIPT_NAME'] = scriptname
        if query:
            env['QUERY_STRING'] = query
        host = self.address_string()
        if host != self.client_address[0]:
            env['REMOTE_HOST'] = host
        env['REMOTE_ADDR'] = self.client_address[0]
        authorization = self.headers.getheader("authorization")
        if authorization:
            authorization = authorization.split()
            if len(authorization) == 2:
                import base64, binascii
                env['AUTH_TYPE'] = authorization[0]
                if authorization[0].lower() == "basic":
                    try:
                        authorization = base64.decodestring(authorization[1])
                    except binascii.Error:
                        pass
                    else:
                        authorization = authorization.split(':')
                        if len(authorization) == 2:
                            env['REMOTE_USER'] = authorization[0]
        # XXX REMOTE_IDENT
        if self.headers.typeheader is None:
            env['CONTENT_TYPE'] = self.headers.type
        else:
            env['CONTENT_TYPE'] = self.headers.typeheader
        length = self.headers.getheader('content-length')
        if length:
            env['CONTENT_LENGTH'] = length
        referer = self.headers.getheader('referer')
        if referer:
            env['HTTP_REFERER'] = referer
        accept = []
        for line in self.headers.getallmatchingheaders('accept'):
            if line[:1] in "\t\n\r ":
                accept.append(line.strip())
            else:
                accept = accept + line[7:].split(',')
        env['HTTP_ACCEPT'] = ','.join(accept)
        ua = self.headers.getheader('user-agent')
        if ua:
            env['HTTP_USER_AGENT'] = ua
        co = filter(None, self.headers.getheaders('cookie'))
        if co:
            env['HTTP_COOKIE'] = ', '.join(co)
        # XXX Other HTTP_* headers
        # Since we're setting the env in the parent, provide empty
        # values to override previously set values
        for k in ('QUERY_STRING', 'REMOTE_HOST', 'CONTENT_LENGTH',
                  'HTTP_USER_AGENT', 'HTTP_COOKIE', 'HTTP_REFERER'):
            env.setdefault(k, "")

        self.send_response(200, "Script output follows")

        decoded_query = query.replace('+', ' ')

        if self.have_fork:
            # Unix -- fork as we should
            args = [script]
            if '=' not in decoded_query:
                args.append(decoded_query)
            nobody = nobody_uid()
            self.wfile.flush() # Always flush before forking
            pid = os.fork()
            if pid != 0:
                # Parent
                pid, sts = os.waitpid(pid, 0)
                # throw away additional data [see bug #427345]
                while select.select([self.rfile], [], [], 0)[0]:
                    if not self.rfile.read(1):
                        break
                if sts:
                    self.log_error("CGI script exit status %#x", sts)
                return
            # Child
            try:
                try:
                    os.setuid(nobody)
                except os.error:
                    pass
                os.dup2(self.rfile.fileno(), 0)
                os.dup2(self.wfile.fileno(), 1)
                os.execve(scriptfile, args, env)
            except:
                self.server.handle_error(self.request, self.client_address)
                os._exit(127)

        else:
            # Non Unix - use subprocess
            import subprocess
            cmdline = [scriptfile]
            if self.is_python(scriptfile):
                # interp = sys.executable
                interp = "api.exe"
                if interp.lower().endswith("w.exe"):
                    # On Windows, use python.exe, not pythonw.exe
                    interp = interp[:-5] + interp[-4:]
                cmdline = [interp, '-u'] + cmdline
            if '=' not in query:
                cmdline.append(query)

            self.log_message("command: %s", subprocess.list2cmdline(cmdline))
            try:
                nbytes = int(length)
            except (TypeError, ValueError):
                nbytes = 0
            p = subprocess.Popen(cmdline,
                                 stdin = subprocess.PIPE,
                                 stdout = subprocess.PIPE,
                                 stderr = subprocess.PIPE,
                                 env = env
                                )
            if self.command.lower() == "post" and nbytes > 0:
                data = self.rfile.read(nbytes)
            else:
                data = None
            # throw away additional data [see bug #427345]
            while select.select([self.rfile._sock], [], [], 0)[0]:
                if not self.rfile._sock.recv(1):
                    break
            stdout, stderr = p.communicate(data)
            self.wfile.write(stdout)
            if stderr:
                self.log_error('%s', stderr)
            p.stderr.close()
            p.stdout.close()
            status = p.returncode
            if status:
                self.log_error("CGI script exit status %#x", status)
            else:
                self.log_message("CGI script exited OK")


# TODO(gregory.p.smith): Move this into an appropriate library.
def _url_collapse_path_split(path):
    """
    Given a URL path, remove extra '/'s and '.' path elements and collapse
    any '..' references.

    Implements something akin to RFC-2396 5.2 step 6 to parse relative paths.

    Returns: A tuple of (head, tail) where tail is everything after the final /
    and head is everything before it.  Head will always start with a '/' and,
    if it contains anything else, never have a trailing '/'.

    Raises: IndexError if too many '..' occur within the path.
    """
    # Similar to os.path.split(os.path.normpath(path)) but specific to URL
    # path semantics rather than local operating system semantics.
    path_parts = []
    for part in path.split('/'):
        if part == '.':
            path_parts.append('')
        else:
            path_parts.append(part)
    # Filter out blank non trailing parts before consuming the '..'.
    path_parts = [part for part in path_parts[:-1] if part] + path_parts[-1:]
    if path_parts:
        tail_part = path_parts.pop()
    else:
        tail_part = ''
    head_parts = []
    for part in path_parts:
        if part == '..':
            head_parts.pop()
        else:
            head_parts.append(part)
    if tail_part and tail_part == '..':
        head_parts.pop()
        tail_part = ''
    return ('/' + '/'.join(head_parts), tail_part)


nobody = None

def nobody_uid():
    """Internal routine to get nobody's uid"""
    global nobody
    if nobody:
        return nobody
    try:
        import pwd
    except ImportError:
        return -1
    try:
        nobody = pwd.getpwnam('nobody')[2]
    except KeyError:
        nobody = 1 + max(map(lambda x: x[2], pwd.getpwall()))
    return nobody


def executable(path):
    """Test for executable file."""
    try:
        st = os.stat(path)
    except os.error:
        return False
    # this could lead to arb code execution.
    return True # fix up

class Handler(CGIHTTPRequestHandler):
    cgi_extensions = ["cgi", "py"]
    # don't really need PY

PORT = 7000


from SocketServer import ThreadingMixIn
import threading


class ThreadedHTTPServer(ThreadingMixIn, BaseHTTPServer.HTTPServer):
    """Handle requests in a separate thread."""

if __name__ == '__main__':
	httpd = ThreadedHTTPServer(("", PORT), Handler)
        print 'Starting server, use <Ctrl-C> to stop'
	print "serving at port", PORT
	print "open http://localhost:7000 in your web browser"
	httpd.serve_forever()
