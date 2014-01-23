from google.appengine.ext import db
from random import shuffle
import FiveEval
import facebook
import jinja2
import json
import os
import urllib2
import webapp2

FACEBOOK_APP_ID = "382044341830181"
FACEBOOK_APP_SECRET = "64eabb93544eb7da72401d3c0b59bce4"

#0 = Ace of Spades
#1 = Ace of Hearts
#2 = Ace of Diamonds
#3 = Ace of Clubs
#
#4 = King of Spades
#5 = King of Hearts
#6 = King of Diamonds
#7 = King of Clubs

jinja_environment = jinja2.Environment(loader=jinja2.FileSystemLoader(os.path.dirname(__file__)))

def game_key(game_name=None):
    return db.Key.from_path('Games', game_name or 'default_game')

class Game(db.Model):
    active_player = db.StringProperty()
    #date = db.DateTimeProperty(auto_now_add=True)
    deck = db.ListProperty(int)
    fbid = db.StringProperty()
    fbids = db.StringListProperty()
    hands = db.StringProperty()
    winner = db.StringProperty()
    
class User(db.Model):
    access_token = db.StringProperty(required=True)
    email = db.StringProperty(required=True)
    fbid = db.StringProperty(required=True)
    name = db.StringProperty(required=True)
    picture = db.StringProperty(required=True)

def create_game(fbid, vs_fbid):
    # create deck
    deck = range(0, 52)
    shuffle(deck)
    # deal the hands
    deal = deck[:13]
    del deck[:13]
    vs_deal = deck[:13]
    del deck[:13]
    
    # create the game object
    game = Game()
    game.active_player = fbid
    game.deck = deck
    game.fbid = fbid
    game.fbids = [fbid, vs_fbid]
    game.hands = json.dumps({fbid:deal, vs_fbid:vs_deal})
    game.put() # save the game object to the datastore
    
    return {'deal':deal, 'game_id': game.key().id()} # return the dealt hand to the game creator 

def calculate_hand_value(hand):
    top = hand["top"]
    middle = hand["middle"]
    bottom = hand["bottom"]
    fiveEval = FiveEval.FiveEval()
    
    top_value = top[0] + top[1] + top[2]
    middle_value = fiveEval.getRankOfFive(middle[0], middle[1], middle[2], middle[3], middle[4]) * 2
    bottom_value = fiveEval.getRankOfFive(bottom[0], bottom[1], bottom[2], bottom[3], bottom[4]) * 3
    
    return top_value + middle_value + bottom_value

class BaseHandler(webapp2.RequestHandler):
    @property
    def current_user(self):
        if not hasattr(self, "_current_user"):
            self._current_user = None
            cookie = facebook.get_user_from_cookie(self.request.cookies, FACEBOOK_APP_ID, FACEBOOK_APP_SECRET)
            if cookie:
                # Store a local instance of the user data so we don't need
                # a round-trip to Facebook on every request
                user = User.get_by_key_name(cookie["uid"])
                if not user:
                    graph = facebook.GraphAPI(cookie["access_token"])
                    profile = graph.get_object(id="me", fields="id, name, username, picture")
                    #friends = graph.get_connections("me", "friends")
                    user = User(access_token=cookie["access_token"],
                                email=profile["username"] + "@facebook.com",
                                fbid=str(profile["id"]),
                                key_name=str(profile["id"]),
                                name=profile["name"],
                                picture=profile["picture"])
                    user.put()
                elif user.access_token != cookie["access_token"]:
                    user.access_token = cookie["access_token"]
                    user.put()
                self._current_user = user
        return self._current_user
    
class Create(BaseHandler):
    def post(self):
        if self.current_user:
            if self.current_user.access_token == self.request.get('access_token'):
                self.response.headers["Access-Control-Allow-Origin"] = "*"
                self.response.headers.add_header('content-type', 'application/json', charset='utf-8')
                self.response.out.write(json.dumps(create_game(self.current_user.fbid, self.request.get('vs_fbid'))))
            else:
                template_values = {
                    'user': self.current_user,
                    'facebook_app_id': FACEBOOK_APP_ID
                }
                template = jinja_environment.get_template('index.html')
                self.response.out.write(template.render(template_values))
            
class Games(BaseHandler):
    def post(self):
        if self.current_user:
            if self.current_user.access_token == self.request.get('access_token'):
                _games = Game.all()
                _games.filter("fbids = ", self.current_user.fbid)
                games = [db.to_dict(game) for game in _games]
                self.response.headers["Access-Control-Allow-Origin"] = "*"
                self.response.headers.add_header('content-type', 'application/json', charset='utf-8')
                self.response.out.write(json.dumps(games))
            else:
                template_values = {
                    'user': self.current_user,
                    'facebook_app_id': FACEBOOK_APP_ID
                }
                template = jinja_environment.get_template('index.html')
                self.response.out.write(template.render(template_values))

class Friends(BaseHandler):
    def post(self):
        if self.current_user:
            if self.current_user.access_token == self.request.get('access_token'):
                graph = facebook.GraphAPI(self.current_user.access_token)
                friends = graph.get_connections("me", "friends")
                self.response.headers["Access-Control-Allow-Origin"] = "*"
                self.response.headers.add_header('content-type', 'application/json', charset='utf-8')
                self.response.out.write(json.dumps(friends['data']))
            else:
                template_values = {
                    'user': self.current_user,
                    'facebook_app_id': FACEBOOK_APP_ID
                }
                template = jinja_environment.get_template('index.html')
                self.response.out.write(template.render(template_values))

class Play(BaseHandler):
    def post(self):
        if self.current_user:
            if self.current_user.access_token == self.request.get('access_token'):
                game = Game.get_by_id(int(self.request.get('game_id')))
                hand = json.loads(self.request.get('hand'))
                
                # determine opponent's fbid
                if game.fbids[0] == self.current_user.fbid:
                    vs_fbid = game.fbids[1]
                else:
                    vs_fbid = game.fbids[0]
                    
                # determine if opponent has already played his hand
                hands = json.loads(game.hands)
                vs_hand = hands[vs_fbid]
                
                #if hasattr(vs_hand, 'top'):
                if 'top' in vs_hand:
                    # already played, evaluate who's the winner
                    hands[self.current_user.fbid] = hand
                    game.hands = json.dumps(hands)
                    game.active_player = None
                    # calculate hands
                    winner = True
                    if calculate_hand_value(hand) > calculate_hand_value(vs_hand):
                        game.winner = self.current_user.fbid
                    else:
                        game.winner = vs_fbid
                        winner = False
                    game.put()
                    self.response.headers["Access-Control-Allow-Origin"] = "*"
                    self.response.headers.add_header('content-type', 'application/json', charset='utf-8')
                    self.response.out.write(json.dumps({"waiting": False, "winner": winner}))
                else:
                    # not yet played, just save current player's hand
                    hands[self.current_user.fbid] = hand
                    game.hands = json.dumps(hands)
                    # set the other player as the active player
                    game.active_player = vs_fbid
                    game.put()
                    self.response.headers["Access-Control-Allow-Origin"] = "*"
                    self.response.headers.add_header('content-type', 'application/json', charset='utf-8')
                    self.response.out.write(json.dumps({"waiting": True}))
            else:
                template_values = {
                    'user': self.current_user,
                    'facebook_app_id': FACEBOOK_APP_ID
                }
                template = jinja_environment.get_template('index.html')
                self.response.out.write(template.render(template_values))

class MainPage(BaseHandler):
    def get(self):
        template_values = {
            'user': self.current_user,
            'facebook_app_id': FACEBOOK_APP_ID
        }
        template = jinja_environment.get_template('index.html')
        self.response.out.write(template.render(template_values))
        
app = webapp2.WSGIApplication([('/', MainPage),
                               ('/create', Create),
                               ('/friends', Friends),
                               ('/games', Games),
                               ('/play', Play),
                               ], debug=True)
