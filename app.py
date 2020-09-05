import datetime
import requests
import redis
import os
import json

from flask import Flask, request
from twilio.rest import Client
from twilio.twiml.voice_response import Play, VoiceResponse, Gather
from twilio.twiml.messaging_response import MessagingResponse
from random import randint

from flask_cors import CORS, cross_origin

app = Flask(__name__)
cors = CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'

# Set up Redis
r = redis.from_url(os.environ.get('REDIS_URL'))

# Set up Twilio client.
account_sid = os.environ.get("ACCOUNT_SID")
auth_token = os.environ.get("AUTH_TOKEN")
client = Client(account_sid, auth_token)

USER_EXPIRY_TIME = 5 * 60 # 5 minutes
EXAM_EXPIRY_TIME = 30 * 60 # 30 minutes

"""
Start an exam. It gets the id of the test and returns a random generated number
to identify this test in the flask server.
Expected data in the request:
{
  "exam_id": ID,
}

Returns:
{
  "sms_id": String,
}
"""
@app.route('/start', methods=['POST'])
@cross_origin()
def start_exam():
  req_data = request.get_json()
  exam_id = req_data['exam_id']
  sms_id = register_exam(exam_id)
  return {
    "sms_id": sms_id,
  }


def register_exam(exam_id):
  sms_id = None
  while sms_id is None or r.exists(sms_id):
    sms_id = str(randint(0, 999999)).zfill(6)
  exam_data = {
    'exam_id': exam_id,
  }
  json_data = json.dumps(exam_data)
  r.set(sms_id, json_data, ex=EXAM_EXPIRY_TIME)
  return sms_id

"""
Gets an sms reply from 'From' phone number with message 'Body'.
There are multiple states possible to be in:

1. The user is registering for the test:

  In this case the user will be sending a 6 digit code. If it exists then
  we should proceed and register it in redis and ask for his name.
  If the code does not exist do nothing.

2. The user is sending his name for the test:

  In this case we will have already received his phone number and have it
  stored in redis. We should store it and proceed to set him as if his next
  message will contain the answer to the first question.

3. The user is answering a question:

  We will send the reply to the server and set the state of the user to the
  next question. If it was the last question then we should delet him from
  redis.
"""
class states:
  REGISTRATION = "REGISTRATION"
  PARTICIPATING = "PARTICIPATING"

def send_answer(phone: str, answer: str, quiz_id: str, ts):
  data = {
    'student_identifier': phone,
    'selection': answer,
    'quiz_id': quiz_id,
    'timestamp': ts.timestamp()
  }

  requests.post(os.environ.get("API_ADDRESS") + 'answers', data=data)

def register_student(name: str, phone: str, quiz_id: str):
  data = {
    'username': name,
    'identifier': phone,
    'quiz_id': quiz_id
  }

  requests.post(os.environ.get("API_ADDRESS") + 'students', data=data)

def handle_answers(phone, answer, ts):
    # If the phone exists then the user might be sending an answer or his name
    if r.exists(phone):
      user_data = r.get(phone)
      user_data = json.loads(user_data)
      exam_data = get_exam_data(user_data['test'])
      quiz_id = exam_data['exam_id']
      if user_data['state'] == states.REGISTRATION:
        user_data['state'] = states.PARTICIPATING
        user_data['name'] = answer
        r.set(phone, json.dumps(user_data), ex=USER_EXPIRY_TIME)

        register_student(answer, phone, quiz_id)
        return f'{phone} se registró con el nombre {answer}'
      elif user_data['state'] == states.PARTICIPATING:
        r.set(phone, json.dumps(user_data), ex=USER_EXPIRY_TIME)
        
        send_answer(phone, answer, quiz_id, ts)
        return None # f'{phone} contestó {answer} a la pregunta {user_data["question"]}'
    else:
      # Register the user for the test initializing the users data
      if r.exists(answer):
        user_data = {
          'state': states.REGISTRATION,
          'test': answer,
        }
        r.set(phone, json.dumps(user_data), ex=USER_EXPIRY_TIME)
        return 'Se ha registrado exitosamente al cuestionario, ahora solo falta el nombre.'
      else:
        return None # 'El cuestionario no existe.'

def get_exam_data(exam_id):
  exam_data = r.get(exam_id)
  exam_data = json.loads(exam_data)
  return exam_data


@app.route("/sms/reply/", methods=['GET', 'POST'])
def sms_reply():
    body = request.values.get('Body', None)
    phone = request.values.get('From', None)

    record = client.messages(request.values.get('SmsSid')).fetch()
    date_created = record.date_created

    text_response = handle_answers(phone, body, date_created)

    # Start our TwiML response.
    resp = MessagingResponse()

    if text_response is not None:
        # Add a text message
        msg = resp.message(text_response)

    return str(resp)

@app.route("/sms/send/<user_phone>", methods=['POST'])
def send_message(user_phone):
    message = client.messages.create(
                body='Hi there!',
                from_=os.environ.get("TWILIO_NUMBER"),
                to=str(user_phone)
            )

    return message.sid

@app.route("/answer/", methods=['GET', 'POST'])
def answer_call():
    """Respond to incoming phone calls with a brief message."""
    phone = request.values.get('From', None)
    # Start our TwiML response
    resp = VoiceResponse()

    # Play music
    # resp.play('http://ocrmirror.org/files/music/remixes/Street_Fighter_2_Guile%27s_Theme_Goes_with_Metal_OC_ReMix.mp3', loop=0)
    
    # Start our <Gather> verb
    if r.exists(phone):
      user_data = r.get(phone)
      user_data = json.loads(user_data)
      if user_data['state'] == states.REGISTRATION:
        resp.say('Di tu nombre por favor', language='es-MX')
        gather = Gather(profanity_filter=True, input='speech', language='es-MX', action='/gather-speech')
      elif user_data['state'] == states.PARTICIPATING:
        gather = Gather(num_digits=1, action='/gather-digits')
    else:
      resp.say('Presiona los seis dígitos del identificador del cuestionario', language='es-MX')
      gather = Gather(num_digits=6, action='/gather-digits')
    resp.append(gather)

    # If the user doesn't select an option, redirect them into a loop
    resp.redirect('/answer/')

    return str(resp)

@app.route('/gather-speech', methods=['GET', 'POST'])
def gather_speech():
    """Processes results from the <Gather> prompt in /voice"""
    # Start our TwiML response
    resp = VoiceResponse()

    phone = request.values.get('From', None)
    date_created = datetime.datetime.now()
    name = request.values.get('SpeechResult', None)

    speech_response = handle_answers(phone, name, date_created)
    resp.say(speech_response, language='es-MX')

    # Go back to call.
    resp.redirect('/answer/')

    return str(resp)

@app.route('/gather-digits', methods=['GET', 'POST'])
def gather_digits():
    """Processes results from the <Gather> prompt in /voice"""
    # Start our TwiML response
    resp = VoiceResponse()

    phone = request.values.get('From', None)
    date_created = datetime.datetime.now()

    # If Twilio's request to our app included already gathered digits,
    # process them
    if 'Digits' in request.values:
        # Get which digit the caller chose
        choice = request.values['Digits']
        print(choice)
        handle_answers(phone, choice, date_created)

    # Go back to call.
    resp.redirect('/answer/')

    return str(resp)

@app.route("/place-call/<user_phone>", methods=['POST'])
def place_call():
  user_phone = user_phone
  call = client.calls.create(
              url='http://demo.twilio.com/docs/voice.xml',
              from_=os.environ.get("TWILIO_NUMBER"),
              to=str(user_phone),
          )

  return call.sids

if __name__ == "__main__":
    app.run(debug=True)
