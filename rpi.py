import RPi.GPIO as GPIO
import time
from grovepi import *
from grove_rgb_lcd import *

# ========================================
# Constants 
# ========================================
# 버튼 핀 번호 설정
btn = [22, 23, 24, 25] # B1(Val+), B2(Next), B3(Val-), B4(Prev)

# 모션감지/부저 핀 번호 설정
PIR_D = 8
BUZZER_D = 3

# --- Advanced Timer Constants ---
STOP_BUTTON_PIN = btn[3] # B4 is the Stop button
BUTTON_DEBOUNCE_S = 0.15
BUTTON_HOLD_S = 2.0         # --- NEW: Hold for 2s to quit ---

PIR_SAMPLES = 3
PIR_INTERVAL_S = 0.1        # Faster PIR read
PIR_MOTION_THRESHOLD = 2
PAUSE_ON_NO_MOTION_S = 8
PAUSE_ON_MOTION_S = 8
# --- End of Advanced Constants ---

# ========================================
# 초기 설정 
# ========================================
menu = [
    [1], # 모드 (m[0][0])
    [30], # 운동시간 (m[1][0])
    [10], # 휴식시간 (m[2][0])
    [3]  # 세트수 (m[3][0])
]

# ========================================
# 하드웨어 초기화 
# ========================================
def init_hardware():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)

    # GPIO 버튼 초기화
    for pin in btn:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    
    # GrovePi PIR, buzzer 초기화
    try:
        pinMode(PIR_D, "INPUT")
        pinMode(BUZZER_D, "OUTPUT")
    except Exception as e:
        print(f"HW Init Error: {e}")

# ========================================
# 부저 함수 
# ========================================
def beep_ms(ms: int):
    try:
        digitalWrite(BUZZER_D, 1)
        time.sleep(ms / 1000.0)
        digitalWrite(BUZZER_D, 0)
    except Exception:
        pass # Ignore errors

def short_beep(times=1, dur_ms=120, gap_ms=80):
    for _ in range(times):
        beep_ms(dur_ms)
        if times > 1:
            time.sleep(gap_ms / 1000.0)

def long_beep(dur_ms=400):
    beep_ms(dur_ms)

# --- NEW: Very short beep for state change ---
def state_change_beep():
    beep_ms(50)
# --- END NEW ---

# --- Sound Mapping ---
ok_sound = short_beep
cancel_sound = lambda: short_beep(times=2, dur_ms=80)
alert_sound = long_beep
start_sound = lambda: short_beep(times=2)
def _noop(*args, **kwargs): pass
play_bgm = pause_bgm = resume_bgm = stop_bgm = _noop
# --- End Sound Mapping ---

# ========================================
# LCD Menu Functions 
# ========================================
def show_mode(m):
    """모드 선택 화면"""
    if m[0][0] == 1:
        setRGB(0, 255, 0)
        setText("Mode 1\nMove Detection")
    else:
        setRGB(0, 100, 255)
        setText("Mode 2\nStay Detection")

def show_exercise(m):
    """운동 시간 설정"""
    setRGB(255, 255, 255)
    setText(f"Exercise Time\n{m[1][0]}s")

def show_rest(m):
    """휴식 시간 설정"""
    setRGB(255, 255, 255)
    setText(f"Rest Time\n{m[2][0]}s")

def show_sets(m):
    """세트 수 설정"""
    mode = m[0][0]
    exer = m[1][0]
    rest = m[2][0]
    sets = m[3][0]
    
    line1 = f"M:{mode} Ex:{exer} R:{rest}"
    line2 = f"Sets:{sets} (Press>)"
    
    setRGB(0, 255, 255)
    setText(f"{line1}\n{line2}")

# ========================================
# Timer Logic 
# ========================================
def get_progress_bar(current, total, width=10):
    if total <= 0:
        return "█" * width
    fill_len = int(width * current / total)
    fill_len = max(0, min(fill_len, width))
    return f'{"█" * fill_len}{"░" * (width - fill_len)}'

def responsive_sleep(duration_s):
    """Waits for 1s, but checks for Stop button 10x."""
    steps = 10
    for _ in range(int(duration_s * steps)):
        if GPIO.input(STOP_BUTTON_PIN) == GPIO.HIGH:
            return True # Stop signal detected
        time.sleep(1 / steps)
    return False

def read_pir_stable():
    """Stable PIR Read"""
    samples = []
    for _ in range(PIR_SAMPLES):
        try:
            val = digitalRead(PIR_D)
            samples.append(val)
        except Exception:
            samples.append(0)
        time.sleep(PIR_INTERVAL_S)
    
    motion_count = sum(samples)
    return 1 if motion_count >= PIR_MOTION_THRESHOLD else 0

def wait_for_resume(required_state):
    """Wait for resume from pause."""
    while GPIO.input(STOP_BUTTON_PIN) == GPIO.LOW:
        motion = read_pir_stable()
        if motion == required_state:
            return False # Resumed normally
        time.sleep(0.3)
    return True # Stop signal detected

def run_exercise_session(m):
    try:
        pinMode(PIR_D, "INPUT") # Init PIR sensor
        time.sleep(0.5)
    except Exception as e:
        print(f"PIR init error: {e}")
    
    mode = m[0][0]
    exercise_s = m[1][0]
    rest_s = m[2][0]
    total_sets = m[3][0]
    
    required_state = 1 if mode == 1 else 0
    
    start_sound() # Plays before Set 1
    if responsive_sleep(0.5): return
    
    for set_num in range(1, total_sets + 1):
        play_bgm() # _noop
        timer_s = 0
        last_valid_state_time = time.time()
        last_pir_state = -1 # --- NEW: Track last PIR state ---
        
        while timer_s < exercise_s:
            motion = read_pir_stable()

            # --- NEW: Beep on state change ---
            if last_pir_state != -1 and motion != last_pir_state:
                state_change_beep() # "Chirp"
            last_pir_state = motion
            # --- END NEW ---
            
            now = time.time()
            status_text = "MOVE" if motion == 1 else "STAY"
            pause_reason = ""
            
            time_since_last_valid = now - last_valid_state_time
            if mode == 1 and motion == 0 and time_since_last_valid >= PAUSE_ON_NO_MOTION_S:
                pause_reason = "No Motion!"
            elif mode == 2 and motion == 1 and time_since_last_valid >= PAUSE_ON_MOTION_S:
                pause_reason = "Motion Detect!"
            elif motion == required_state:
                last_valid_state_time = now
            
            if pause_reason:
                pause_bgm() # _noop
                cancel_sound() # Beep! Beep!
                setRGB(255, 165, 0)
                setText(f"PAUSED\n{pause_reason}")
                if wait_for_resume(required_state):
                    stop_bgm() # _noop
                    setRGB(255, 0, 0)
                    setText("Stopped\nReturning...")
                    time.sleep(1.5)
                    return
                ok_sound() # Beep!
                resume_bgm() # _noop
                last_valid_state_time = time.time()
                last_pir_state = -1 # Reset state after resume
            
            remaining_s = exercise_s - timer_s
            bar = get_progress_bar(timer_s, exercise_s, 10)
            line1 = f"M{mode} Set {set_num}/{total_sets} {status_text}"
            line2 = f"{bar} {remaining_s}s"
            setRGB(0, 255, 0)
            setText(f"{line1}\n{line2}")
            
            if responsive_sleep(1):
                stop_bgm() # _noop
                setRGB(255, 0, 0)
                setText("Stopped\nReturning...")
                time.sleep(1.5)
                return
            
            timer_s += 1
            
        stop_bgm() # _noop
        alert_sound() # Long beep! (Exercise -> Rest)
        
        if set_num < total_sets:
            for timer_s in range(rest_s):
                remaining_s = rest_s - timer_s
                bar = get_progress_bar(timer_s, rest_s, 10)
                setRGB(0, 150, 255)
                setText(f"Rest {set_num}/{total_sets}\n{bar} {remaining_s}s")
                
                if responsive_sleep(1):
                    setRGB(255, 0, 0)
                    setText("Stopped\nReturning...")
                    time.sleep(1.5)
                    return
            
            start_sound() # Double beep! (Rest -> Next Exercise)
                
    setRGB(255, 0, 255)
    setText("Complete!\nPress any btn")
    
    while all(GPIO.input(p) == GPIO.LOW for p in btn):
        time.sleep(0.05)
    time.sleep(BUTTON_DEBOUNCE_S)

def start_exercise(m):
    """운동 시작"""
    print("\n=== 운동 시작 ===")
    print(f"Mode: {m[0][0]}, 운동: {m[1][0]}s, 휴식: {m[2][0]}s, 세트: {m[3][0]}")
    
    #운동 함수 시작
    run_exercise_session(m) 
    
    print("=== 운동 종료 ===")
    setRGB(0, 255, 0)
    setText("Back to Menu")
    time.sleep(0.5)
    return 0  # 운동 후 다시 메뉴로 돌아감 (step = 0)

# ========================================
# Main Loop 
# ========================================
menu_funcs = [show_mode, show_exercise, show_rest, show_sets]
step = 0

setRGB(0,255,0)
print("mode start! (Ctrl+C로 종료)")
init_hardware()
menu_funcs[step](menu)

try:
    while True:
        # --- Button 1 (Val+) ---
        if GPIO.input(btn[0]) == GPIO.HIGH:
            ok_sound() # Beep on button press
            match step:
                case 0: # Mode
                    menu[0][0] = 1 if menu[0][0] == 2 else 2
                case 1: # Exercise
                    menu[1][0] += 10
                case 2: # Rest
                    menu[2][0] += 5
                case 3: # Sets
                    menu[3][0] += 1
            
            menu_funcs[step](menu)
            time.sleep(BUTTON_DEBOUNCE_S)
        
        # --- Button 2 (Next) ---
        elif GPIO.input(btn[1]) == GPIO.HIGH:
            ok_sound() # Beep on button press
            step = step + 1
            if step >= len(menu_funcs):  # 3을 넘으면 운동 시작
                step = start_exercise(menu)
            
            menu_funcs[step](menu)
            time.sleep(BUTTON_DEBOUNCE_S)

        # --- Button 3 (Val-) ---
        elif GPIO.input(btn[2]) == GPIO.HIGH:
            ok_sound() # Beep on button press
            match step:
                case 0: # Mode
                    menu[0][0] = 1 if menu[0][0] == 2 else 2
                case 1: # Exercise
                    menu[1][0] = max(10, menu[1][0] - 10)
                case 2: # Rest
                    menu[2][0] = max(5, menu[2][0] - 5)
                case 3: # Sets
                    menu[3][0] = max(1, menu[3][0] - 1)
            
            menu_funcs[step](menu)
            time.sleep(BUTTON_DEBOUNCE_S)

        # --- Button 4 (Prev / HOLD TO QUIT) ---
        elif GPIO.input(btn[3]) == GPIO.HIGH:
            press_start = time.time()
            
            # --- NEW: Check for long press ---
            while GPIO.input(btn[3]) == GPIO.HIGH:
                if time.time() - press_start > BUTTON_HOLD_S:
                    print("\n=== Quit Program (Hold B4) ===")
                    long_beep()
                    raise KeyboardInterrupt 
                time.sleep(0.05)
            # --- END NEW ---
            
            # If it was just a short press, run the "Prev"
            if time.time() - press_start < 0.5:
                ok_sound() # Beep on button press
                step -= 1
                if step < 0:  # 음수 방지
                    step = 0
                menu_funcs[step](menu)
                
            time.sleep(BUTTON_DEBOUNCE_S)
            
        else:
            time.sleep(0.01)

except KeyboardInterrupt:
    print("\n종료합니다.")
finally:
    GPIO.cleanup()
    setRGB(128, 128, 128)
    setText("Goodbye!")