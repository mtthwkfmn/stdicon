# Paul Tarjan : http://paulisageek.com

import os
import mimetypes
import logging
import simplejson
from urllib import unquote

import wsgiref.handlers

from google.appengine.api import users
from google.appengine.api import images
from google.appengine.api import memcache
from google.appengine.api import urlfetch

from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template

from datetime import timedelta, datetime

mimetypes.knownfiles.append("mime.types")
mimetypes.init(mimetypes.knownfiles)


class Set(db.Model):
    name = db.StringProperty(required=True)
    modified = db.DateTimeProperty(auto_now=True)
    created = db.DateTimeProperty(auto_now_add=True)
    
class Icon(db.Model):
    mimetype = db.StringProperty(required=True)
    set = db.ReferenceProperty(Set, required=True)
    contents = db.BlobProperty()
    modified = db.DateTimeProperty(auto_now=True)
    created = db.DateTimeProperty(auto_now_add=True)

class IndexHandler(webapp.RequestHandler):
    def get(self):
        template_values = {}
        template_values['sets'] = Set.all().order("name")

        path = os.path.join(os.path.dirname(__file__), 'index.html')
        self.response.out.write(template.render(path, template_values))

class SetHandler(webapp.RequestHandler):
    def get(self, setname):
        set = Set.all().filter("name =", setname).get()
        if not set :
            self.response.set_status(404)
            self.response.out.write("Set '%s' not found" % (setname))
            return False
            
        template_values = {}
        template_values['set'] = set.name
        template_values['icons'] = Icon.all().filter("set =", set).order("mimetype")

        path = os.path.join(os.path.dirname(__file__), 'icon_list.html')
        self.response.out.write(template.render(path, template_values))

class IconHandler(webapp.RequestHandler):
    def error(self, status, msg="") :
        default = self.request.get("default")
        if not default :
            self.response.set_status(status)
            self.response.out.write(msg)
        else :
            try :
                image = None
                # image = memcache.get("default_image_" + default)
                if not image :
                    image = urlfetch.fetch(default).content
                    memcache.set("default_image_" + default, image, 60 * 60) # 1 hour
                return self.image(image, cache=False)

            except urlfetch.Error, why :
                self.response.set_status(404)
                self.response.out.write("Default image error: %s : %s" % (default, why))

    def get(self, default_set="crystal"):
        image = memcache.get("image_" + self.request.url)
        if image : 
            return self.respond_image(image)

        # path is urlencoded with + being %2B
        path = unquote(self.request.path)

        parts = path.split("/")[1:]
        if len(parts) == 1 :
            setname = default_set
            mimetype = parts[0]
        else :
            setname = parts[0]
            mimetype = "/".join(parts[1:])

        set = Set.all().filter("name = ", setname).get()
        if not set :
            setname = default_set
            set = Set.all().filter("name = ", setname).get()
            mimetype = "/".join(parts)

        guess, encoding = mimetypes.guess_type("dummy." + mimetype)
        if guess :
            logging.info("Guessed '%s' for '%s'" % (guess, mimetype))
            mimetype = guess

        icon = Icon.all().filter("set =", set).filter("mimetype =", mimetype).get()
        if not icon :
            parts = mimetype.split("/")
            if len(parts) >= 1 :
                generic_mimetype = parts[0] + "/x-generic"
                icon = Icon.all().filter("set =", set).filter("mimetype =", generic_mimetype).get()

            if not icon :
                return self.error(404, "Icon '%s' not found in '%s' set" % (mimetype, setname))

        if not icon.contents :
            return self.error(500, "'%s' from '%s' has 0 bytes" % (mimetype, setname))

        return self.image(icon.contents)

    def image(self, contents, cache=True) :
            
        size = self.request.get("size")
        if size :
            boom = size.split("x")
            if len(boom) == 1:
                h = size
                w = size
            else :
                h = boom[0]
                w = boom[1]
            
            try :
                image = images.resize(contents, int(w), int(h))
            except ValueError, why :
                image = contents

            if cache :
                memcache.add("image_" + self.request.url, image)

        else :
            image = contents

        return self.respond_image(image)

    def respond_image(self, image) :
        self.response.headers['Content-Type'] = 'image/png'
        hours = 24*7
        then = timedelta(hours=hours) + datetime.now()
        self.response.headers['Expires'] = then.strftime("%a, %d %b %Y %H:%M:%S GMT")
        self.response.headers['Cache-Control'] = 'max-age=%d' % int(3600*hours)
        self.response.out.write(image)
        return True

    def post(self) :
        return get()

class FaviconHandler(IconHandler):
    def get(self):
        icon = Icon.all().filter("mimetype =", "text/html").get()
        return self.respond_image(icon.contents)

class CreateHandler(webapp.RequestHandler):
    def get(self):
        user = users.get_current_user()
        if not user :
            return self.redirect(users.create_login_url(self.request.url))
            
        if not users.is_current_user_admin() :
            logging.warning("Non-admin found the create url : %s", user)
            return self.redirect("/")

        template_values = {}
        template_values['sets'] = Set.all().order("name")

        path = os.path.join(os.path.dirname(__file__), 'create.html')
        self.response.out.write(template.render(path, template_values))

    def post(self) :
        if not users.is_current_user_admin() :
            return self.redirect("/")

        setname = self.request.get("setname")
        if setname :
            Set(name=setname).put()

        return self.get()

class CreateIconHandler(webapp.RequestHandler):
    def get(self, setname):
        if not users.is_current_user_admin() :
            return self.redirect("/")

        set = Set.all().filter("name =", setname).get()
        if not set :
            self.response.set_status(404)
            self.response.out.write("Set '%s' not found" % (setname))
            return False
            
        template_values = {}
        template_values['set'] = set.name
        template_values['icons'] = Icon.all().filter("set =", set).order("mimetype")

        path = os.path.join(os.path.dirname(__file__), 'create_icon.html')
        self.response.out.write(template.render(path, template_values))

    def post(self, setname) :
        if not users.is_current_user_admin() :
            return self.redirect("/")

        mimetype = self.request.get("mimetype")
        setname = self.request.get("set")
        contents = self.request.get("contents")
        if mimetype and set and contents :
            icon = Icon(mimetype=mimetype, set=Set.all().filter("name =", setname).get())
            icon.contents = contents
            icon.put()

        return self.get(setname)

class MimetypesHandler(webapp.RequestHandler):
    def get(self) :
        keys = mimetypes.types_map.keys()
        keys.sort()
        map = []
        for k in keys :
            map.append({k: mimetypes.types_map[k]})
        if self.request.get("format") != "xml" :
            self.response.headers['Content-Type'] = 'application/json'
            self.response.out.write(simplejson.dumps(map))
        else :
            self.response.headers['Content-Type'] = 'application/xml'
            o = self.response.out
            o.write("<mimetypes>")
            for f in map :
                k = f.keys()[0]
                v = f[k]
                o.write("<file><ext>%s</ext><mimetype>%s</mimetype></file>" % (k,v))
            o.write("</mimetypes>")

class MimetypeLookupHandler(webapp.RequestHandler):
    def get(self, method, type) :
        if method == "ext" :
            guess, handler = mimetypes.guess_type("dummy." + type)
            if guess :
                self.response.out.write(guess)
            else :
                self.response.set_status(404)
                self.response.out.write("Extension '%s' has no known mimetype" % (type))
        elif method == "mimetype" :
            ext = mimetypes.guess_extension(type)
            if ext and ext[0] == "." :
                self.response.out.write(ext[1:])
            else :
                self.response.set_status(404)
                self.response.out.write("Mimetype '%s' has no known extension" % (type))
            
            
def main():
  application = webapp.WSGIApplication([
                                        (r'/', IndexHandler),
                                        (r'/favicon.ico', FaviconHandler),
                                        (r'/(.+)/', SetHandler),
                                        (r'/create/?', CreateHandler),
                                        (r'/create/(.+)', CreateIconHandler),
                                        (r'/mimetypes', MimetypesHandler),
                                        (r'/(ext|mimetype)/(.+)', MimetypeLookupHandler),
                                        (r'/.+', IconHandler),
                                       ],
                                       debug=True)
  wsgiref.handlers.CGIHandler().run(application)

if __name__ == '__main__':
  main()
