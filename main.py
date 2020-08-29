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

app = Flask(__name__)

# Set up Redis
r = redis.Redis(host=os.environ['REDIS_HOST'], port=os.environ['REDIS_PORT'], db=0)

# Set up Twilio client.
account_sid = os.environ.get("ACCOUNT_SID")
auth_token = os.environ.get("AUTH_TOKEN")
client = Client(account_sid, auth_token)

"""
Start an exam. It gets the id of the test and returns a random generated number
to identify this test in the flask server.
Expected data in the request:
{
  "exam_id": ID,
  "num_questions": Number,
  "questions": [Number],
}

Returns:
{
  "sms_id": String,
}
"""
@app.route('/start', methods=['POST'])
def start_exam():
  req_data = request.get_json()
  exam_id = req_data['exam_id']
  num_questions = req_data['num_questions']
  questions = req_data['questions']
  sms_id = register_exam(exam_id, num_questions, questions)
  return {
    "sms_id": sms_id,
  }


def register_exam(exam_id, num_questions, questions):
  sms_id = None
  while sms_id is None or r.exists(sms_id):
    sms_id = str(randint(0, 999999)).zfill(6)
  exam_data = {
    'exam_id': exam_id,
    'num_questions': num_questions,
    'questions': questions,
  }
  json_data = json.dumps(exam_data)
  r.set(sms_id, json_data)
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

def send_answer(phone: str, answer: str, question_id: str, ts):
  data = {
    'student_identifier': phone,
    'question': question_id,
    'selection': answer,
    'timestamp': ts
  }

  requests.post(os.environ.get("API_ADDRESS") + 'answers', data=data)

def register_student(name: str, phone: str, quiz_id: str):
  data = {
    'username': name,
    'identifier': phone,
    'quiz_id': quiz_id
  }

  requests.post(os.environ.get("API_ADDRESS") + 'student', data=data)

def handle_answers(phone, answer, ts):
    # If the phone exists then the user might be sending an answer or his name
    print('handle_answers')
    if r.exists(phone):
      print('enrolled in quizz')
      user_data = r.get(phone)
      user_data = json.loads(user_data)
      exam_data = get_exam_data(user_data['test'])
      quiz_id = exam_data['exam_id']
      if user_data['state'] == states.REGISTRATION:
        print('register user')
        user_data['state'] = states.PARTICIPATING
        user_data['name'] = answer
        user_data['question'] = 0
        print(f'{phone} registered to participate as {answer}')
        r.set(phone, json.dumps(user_data))

        register_student(answer, phone, user_data['test'])
      elif user_data['state'] == states.PARTICIPATING:
        print('send answer')
        question_id = exam_data['questions'][user_data['question']]
        print(f'{phone} answered {answer} to question {user_data["question"]}')
        user_data['question'] += 1
        if user_data['question'] == exam_data['num_questions']:
          # This user has finished the exam, delete data
          r.delete(phone)
        else:
          r.set(phone, json.dumps(user_data))
        
        send_answer(phone, answer, ts)
    else:
      print('enroll quizz')
      # Register the user for the test initializing the users data
      if r.exists(answer):
        user_data = {
          'state': states.REGISTRATION,
          'test': answer,
        }
        print(phone)
        r.set(phone, json.dumps(user_data))
        print(r.exists(phone))

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

    # Start our TwiML response.
    resp = MessagingResponse()

    handle_answers(phone, body, date_created)
      
    # Add a text message
    msg = resp.message("Your Phone Number is: %s" % phone)

    return str(resp)

@app.route("/sms/send/<user_phone>", methods=['POST'])
def send_message():
    user_phone = user_phone
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
        resp.say('Please say your name')
        gather = Gather(profanity_filter=True, input='speech', language='es-MX', action='/gather-speech')
      elif user_data['state'] == states.PARTICIPATING:
        gather = Gather(num_digits=1, action='/gather-digits')
    else:
      resp.say('Please enter the 6 digit quizz I D.')
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

    print(request.values)

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

    print(request.values)

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
