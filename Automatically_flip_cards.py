from anki import hooks, sound
from aqt import mw, utils
from aqt.qt import *
from aqt import progress
import time
from aqt.utils import getText
from aqt.reviewer import Reviewer
import string
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen import contextlib
import platform
import wave
import time
import os, subprocess
import anki.sound
from threading import Event
from threading import Condition
from threading import Thread
from threading import Thread
from mutagen.Queue import Queue, Empty
from mutagen.Queue import Queue
from anki.sound import play
from anki.sound import mplayerQueue, mplayerClear, mplayerEvt
from anki.sound import MplayerMonitor
from anki.hooks import addHook, wrap
from aqt.utils import showInfo
import re
# from PyQt4 import QtGui

audio_speed = 1.0
regex = r"sound:[^\.\s]*\.(?:mp3|wav|m4a)"
mode = 0 # 1: add times in all audios, 0: get time in the first audio
stdoutQueue = Queue()

class CustomMessageBox(QMessageBox):

    def __init__(self, *__args):
        QMessageBox.__init__(self, parent=mw.app.activeWindow() or mw)
        self.timeout = 0
        self.autoclose = False
        self.currentTime = 0

    def showEvent(self, QShowEvent):
        self.currentTime = 0
        if self.autoclose:
            self.startTimer(1000)

    def timerEvent(self, *args, **kwargs):
        self.currentTime += 1
        if self.currentTime >= self.timeout:
            self.done(0)

    @staticmethod
    def showWithTimeout(timeoutSeconds, message, title, icon=QMessageBox.Information, buttons=QMessageBox.Ok):
        w = CustomMessageBox()
        w.autoclose = True
        w.timeout = timeoutSeconds
        w.setText(message)
        w.setWindowTitle(title)
        w.setIcon(icon)
        sg = w.parent().rect()
        x = sg.width() / 2 - w.pos().x() - w.rect().width()
        y = sg.height() / 2 - w.pos().y() - w.rect().height()
        w.move(x, y)
        w.exec_()


class TimeKeep(object):
    time_limit_question = 0
    time_limit_answer = 0
    addition_time = 0
    addition_time_question = 0
    addition_time_answer = 0
    add_time = True
    play = False
    timer = None
    is_question = True
    adjust_both = False

    def __init__(self):
        pass


def find_audio_fields(card):
    def check(value):
        suffixs = ['.mp3', '.m4a', '.wav']
        res = False
        for suffix in suffixs:
            if suffix in value: res = True
        return res and "[sound:" in value

    audio_fields = []
    for field, value in card.note().items():
        if check(value):
            audio_fields.append(field)
    return audio_fields


def split_audio_fields(card, m, audio_fields):
    def helper(q):
        q_times = []
        start = 0
        while True:
            s = q.find('{{', start)
            if s == -1: break
            e = q.find('}}', s)
            if e != -1:
                if q[s + 2:e] in audio_fields:
                    q_times.append(q[s + 2:e][:])
                start = e + 2
            else: break
        return q_times

    question_audio_fields = []
    answer_audio_fields = []
    if card is not None:
        t = m['tmpls'][card.ord]
        q = t.get('qfmt')
        a = t.get('afmt')
        question_audio_fields.extend(helper(q))
        answer_audio_fields.extend(helper(a))
    return question_audio_fields, answer_audio_fields


def calculate_file_length(suffix, mp):
    if suffix == 'mp3':
        audio = MP3(mp)
        length = str(audio.info.length)
        time = int(float(length) * 1000)
    elif suffix == 'wav':
        with contextlib.closing(wave.open(mp, 'r')) as f:
            frames = f.getnframes()
            rate = f.getframerate()
            length = frames / float(rate)
            time = int(float(length) * 1000)
    elif suffix == 'm4a':
        audio = MP4(mp)
        length = str(audio.info.length)
        time = int(float(length) * 1000)
    return time


def calculate_time(card, media_path, time_fields):
    time = 0
    audios = []
    for field, value in card.note().items():
        if field in time_fields:
            position = 0
            audio_names_field = []
            while True:
                position = value.find("[sound:", position)
                if position == -1:
                    break
                e = value.find("]", position)
                if e == -1:
                    break
                audio_names_field.append(value[position + 1:e])
                position = e
            audios.extend(audio_names_field)
    if mode == 0:
        audios = audios[:1]
    for v in audios:
        mp = media_path + v[6:]
        time += calculate_file_length(v[-3:], mp)
    return time


def set_time_limit():
    def helper(audio_fields):
        time = 0
        if len(audio_fields) > 0:
            time = calculate_time(card, media_path, audio_fields)
        if time == 0:
            time = 1500
        return time

    global audio_speed
    card = mw.reviewer.card
    if card is not None:
        note = card.note()
        model = note.model()
        audio_fields = find_audio_fields(card)
        audio_fields_q, audio_fields_a = split_audio_fields(card, model, audio_fields)
        if platform.system() == 'Windows':
            media_path = mw.col.path.rsplit('\\', 1)[0] + '\\collection.media\\'
        else:
            media_path = mw.col.path.rsplit('/', 1)[0] + '/collection.media/'
        time1 = helper(audio_fields_q)
        time2 = helper(audio_fields_a)
        TimeKeep.time_limit_question =  time1 + time2 / audio_speed + int(TimeKeep.addition_time * 1000 + TimeKeep.addition_time_question * 1000) 
        TimeKeep.time_limit_answer =  (time2 / audio_speed) * 2 + int(TimeKeep.addition_time * 1000 + TimeKeep.addition_time_answer * 1000)


def show_answer():
    if mw.reviewer and mw.col and mw.reviewer.card and mw.state == 'review':
        TimeKeep.is_question = False
        mw.reviewer._showAnswer()
    if TimeKeep.play:
        TimeKeep.timer = mw.progress.timer(TimeKeep.time_limit_answer, change_card, False)


def change_card():
    if mw.reviewer and mw.col and mw.reviewer.card and mw.state == 'review':
        TimeKeep.is_question = True
        mw.reviewer._answerCard(mw.reviewer._defaultEase())


def check_valid_card():
    # utils.showInfo("Check Valid Card")
    card = mw.reviewer.card
    if card is None: return False
    if card.note() is None: return False
    return True


def show_question():
    if not check_valid_card():
        return
    set_time_limit()
    if TimeKeep.play:
        TimeKeep.timer = mw.progress.timer(TimeKeep.time_limit_question, show_answer, False)


def start():
    if TimeKeep.play: return
    CustomMessageBox.showWithTimeout(0.5, "Automatically flip cards: start", "Message")
    sound.clearAudioQueue()
    if TimeKeep.add_time:
        set_time_limit()
        TimeKeep.add_time = False
    hooks.addHook("showQuestion", show_question)
    TimeKeep.play = True
    if mw.reviewer.state == 'question':
        if check_valid_card():
            show_answer()
    elif mw.reviewer.state == 'answer':
        if check_valid_card():
            change_card()


def stop():
    global audio_speed
    if not TimeKeep.play: return
    CustomMessageBox.showWithTimeout(0.5, "Automatically flip cards: stop", "Message")
    TimeKeep.play = False
    hooks.remHook("showQuestion",show_question)
    if TimeKeep.timer is not None: TimeKeep.timer.stop()
    TimeKeep.timer = None
    audio_speed = 1.0


def add_time_base(t=1):
    if TimeKeep.play:
        stop()
    if t == 1:
        at = utils.getText("Add additional time for questions and answers")
    elif t == 2:
        at = utils.getText("Add additional time for questions")
    else:
        at = utils.getText("Add additional time for answers")
    if at is not None and len(at) > 0:
        try:
            at = float(at[0])
        except:
            utils.showInfo('You must enter a positive number!')
            return
    else:
        return
    if at >= 0 and at <= 20:
        if t == 1:
            TimeKeep.addition_time = at
            utils.showInfo('Set additional time for questions and answers')
        elif t == 2:
            TimeKeep.addition_time_question = at
            utils.showInfo('Set additional time for questions')
        else:
            TimeKeep.addition_time_answer = at
            utils.showInfo('Set additional time for answers')
        TimeKeep.add_time = True
    else: utils.showInfo('Invalid additional time. Time value must be in the range 0 to 20')


def add_time():
    add_time_base(1)


def add_time_question():
    add_time_base(2)


def add_time_answer():
    add_time_base(3)


def switch_mode():
    global mode
    mode = 1 - mode
    if mode == 0:
        utils.showInfo("Get time of the first audio.")
    else:
        utils.showInfo("Get time of all audios.")


def enqueue_output(out, queue):
    for line in iter(out.readline, b''):
        queue.put(line)
    out.close()


def my_keyHandler(self, evt):
    #global messageBuff
    global audio_speed, audio_replay
    
    key = unicode(evt.text())

    if key == "0":
        audio_speed = 1.0
    elif key == "{":
        TimeKeep.adjust_both = False
        audio_speed = max(0.1, audio_speed - 0.1)
    elif key == "}":
        TimeKeep.adjust_both = False
        audio_speed = min(4.0, audio_speed + 0.1)
    elif key == "<":
        TimeKeep.adjust_both = True
        audio_speed = max(0.1, audio_speed - 0.1)
    elif key == ">":
        TimeKeep.adjust_both = True
        audio_speed = min(4.0, audio_speed + 0.1)
    if key in "0\{\}<>":    
        if anki.sound.mplayerManager is not None and not TimeKeep.is_question:
            if anki.sound.mplayerManager.mplayer is not None: 
                anki.sound.mplayerManager.mplayer.stdin.write("af_add scaletempo=stride=10:overlap=0.8\n")
                anki.sound.mplayerManager.mplayer.stdin.write(("speed_set %f \n" % audio_speed))
    
    if key == "p":
        anki.sound.mplayerManager.mplayer.stdin.write("pause\n")
    if key == "r":
        anki.sound.mplayerClear = True


    # Clear Message Buffer (for debugging)
    #if key == "8":
    #    messageBuff = ""
    
    # Show Message Buffer (for debugging)
    #if key == "9":
    #    sys.stderr.write(messageBuff)
            
def my_runHandler(self):
    #global messageBuff
    global currentlyPlaying
    
    self.mplayer = None
    self.deadPlayers = []
    
    while 1:
        anki.sound.mplayerEvt.wait()
        anki.sound.mplayerEvt.clear()
        # clearing queue?
        if anki.sound.mplayerClear and self.mplayer:
            try:
                self.mplayer.stdin.write("stop\n")
            except:
                # mplayer quit by user (likely video)
                self.deadPlayers.append(self.mplayer)
                self.mplayer = None
        
        # loop through files to play
        while anki.sound.mplayerQueue:
            # ensure started
            if not self.mplayer:
                my_startProcessHandler(self)
                #self.startProcess()
                
            # pop a file
            try:
                item = anki.sound.mplayerQueue.pop(0)      
            except IndexError:
                # queue was cleared by main thread
                continue
            if anki.sound.mplayerClear:
                anki.sound.mplayerClear = False
                extra = ""
            else:
                extra = " 1"
            cmd = 'loadfile "%s"%s\n' % (item, extra)
            
            try:
                self.mplayer.stdin.write(cmd)
            except:
                # mplayer has quit and needs restarting
                self.deadPlayers.append(self.mplayer)
                self.mplayer = None
                my_startProcessHandler(self)
                #self.startProcess()
                self.mplayer.stdin.write(cmd)

            if TimeKeep.adjust_both and (abs(audio_speed - 1.0) > 0.01 or audio_speed == 1.0):
                self.mplayer.stdin.write("af_add scaletempo=stride=10:overlap=0.8\n")
                self.mplayer.stdin.write("speed_set %f \n" % audio_speed)
                self.mplayer.stdin.write("seek 0 1\n")
            elif (abs(audio_speed - 1.0) > 0.01 or audio_speed == 1.0) and not TimeKeep.is_question:
                self.mplayer.stdin.write("af_add scaletempo=stride=10:overlap=0.8\n")
                self.mplayer.stdin.write("speed_set %f \n" % audio_speed)
                self.mplayer.stdin.write("seek 0 1\n")
            elif TimeKeep.is_question:
                self.mplayer.stdin.write("af_add scaletempo=stride=10:overlap=0.8\n")
                self.mplayer.stdin.write("speed_set %f \n" % 1.0)
                self.mplayer.stdin.write("seek 0 1\n")

            # Clear out rest of queue
            extraOutput = True
            while extraOutput:
                try:
                    extraLine = stdoutQueue.get_nowait()
                    #messageBuff += "ExtraLine: " + line
                except Empty:
                    extraOutput = False
            
            # Wait until the file finished playing before adding the next file
            finishedPlaying = False
            while not finishedPlaying and not anki.sound.mplayerClear:
                # poll stdout for an 'EOF code' message
                try:
                    line = stdoutQueue.get_nowait()
                    #messageBuff += line
                except Empty:
                    # nothing, sleep for a bit
                    finishedPlaying = False
                    time.sleep(0.05)
                else:
                    # check the line
                    #messageBuff += line
                    lineParts = line.split(':')
                    if lineParts[0] == 'EOF code':
                        finishedPlaying = True
            
            # Clear out rest of queue
            extraOutput = True
            while extraOutput:
                try:
                    extraLine = stdoutQueue.get_nowait()
                    #messageBuff += "ExtraLine: " + line
                except Empty:
                    extraOutput = False
            
        # if we feed mplayer too fast it loses files
        time.sleep(0.1)
        # end adding to queue
                
        # wait() on finished processes. we don't want to block on the
        # wait, so we keep trying each time we're reactivated
        def clean(pl):
            if pl.poll() is not None:
                pl.wait()
                return False
            else:
                showInfo("Clean")
                return True
        self.deadPlayers = [pl for pl in self.deadPlayers if clean(pl)]


def my_startProcessHandler(self):
    try:
        cmd = anki.sound.mplayerCmd + ["-slave", "-idle", '-msglevel', 'all=0:global=6']
        devnull = file(os.devnull, "w")
        
        # open up stdout PIPE to check when files are done playing
        self.mplayer = subprocess.Popen(
            cmd, startupinfo=anki.sound.si, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=devnull)

        # setup 
        t = Thread(target=enqueue_output, args=(self.mplayer.stdout, stdoutQueue))
        t.daemon = True
        t.start()
    except OSError:
        anki.sound.mplayerEvt.clear()
        raise Exception("Did you install mplayer?")


afc = mw.form.menuTools.addMenu("Automatically flip card")

action = QAction("Start automatically flipping card", mw)
action.setShortcut('j')
action.triggered.connect(start)
afc.addAction(action)

action = QAction("Stop automatically flipping card", mw)
action.setShortcut('k')
action.triggered.connect(stop)
afc.addAction(action)

action = QAction("Start automatically flipping card", mw)
action.setShortcut('Ctrl+j')
action.triggered.connect(start)
afc.addAction(action)

action = QAction("Stop automatically flipping card", mw)
action.setShortcut('Ctrl+k')
action.triggered.connect(stop)
afc.addAction(action)

action = QAction("Switch mode", mw)
action.setShortcut('Ctrl+y')
action.triggered.connect(switch_mode)
afc.addAction(action)

action = QAction("Add additional time", mw)
action.setShortcut('Shift+J')
action.triggered.connect(add_time)
afc.addAction(action)

action = QAction("Add additional time to questions", mw)
action.setShortcut('Shift+D')
action.triggered.connect(add_time_question)
afc.addAction(action)

action = QAction("Add additional time to answers", mw)
action.setShortcut('Shift+F')
action.triggered.connect(add_time_answer)
afc.addAction(action)

Reviewer._keyHandler = wrap(Reviewer._keyHandler, my_keyHandler)
MplayerMonitor.run = my_runHandler
MplayerMonitor.startProcess = my_startProcessHandler
