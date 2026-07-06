from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, date
import json
import os
import calendar as pycalendar

app = Flask(__name__)
app.secret_key = os.environ.get("IVCALEND_SECRET_KEY", "ivcalend-local-secret")

DATA_FILE = "data.json"

MONTH_NAMES = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
               "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
DAY_NAMES = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]


def format_date_ru(value):
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return value
    return parsed.strftime("%d.%m.%Y")


def parse_date_ru(value):
    value = value.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def normalize_time(value):
    value = value.strip()
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%H:%M").strftime("%H:%M")
    except ValueError:
        return ""


def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "events": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def current_user():
    return session.get("user")


def current_team():
    data = load_data()
    user = current_user()
    if user and user in data["users"]:
        return data["users"][user]["team"]
    return None


@app.context_processor
def inject_globals():
    return {
        "theme": session.get("theme", "dark"),
        "logged_user": current_user(),
        "logged_team": current_team(),
        "format_date_ru": format_date_ru
    }


@app.route("/theme/toggle")
def toggle_theme():
    current = session.get("theme", "dark")
    new_theme = "light" if current == "dark" else "dark"
    session["theme"] = new_theme
    if request.headers.get("X-Theme-Request") == "smooth":
        return jsonify({"theme": new_theme})
    next_page = request.args.get("next") or url_for("landing")
    return redirect(next_page)


@app.route("/")
def landing():
    if current_user():
        team = current_team()
        if team:
            return redirect(url_for("calendar_page"))
        return redirect(url_for("team_page"))
    return render_template("landing.html")


@app.route("/auth")
def auth_page():
    tab = request.args.get("tab", "login")
    return render_template("auth.html", tab=tab)


@app.route("/register", methods=["POST"])
def register():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    password2 = request.form.get("password2", "")

    data = load_data()

    if len(username) < 2:
        flash("Введите имя пользователя")
        return redirect(url_for("auth_page", tab="register"))

    if username in data["users"]:
        flash("Такой пользователь уже есть")
        return redirect(url_for("auth_page", tab="register"))

    has_digit = any(ch.isdigit() for ch in password)
    has_letter = any(ch.isalpha() for ch in password)
    if len(password) < 8 or not has_digit or not has_letter:
        flash("Пароль должен быть не короче 8 символов и содержать букву и цифру")
        return redirect(url_for("auth_page", tab="register"))

    if password != password2:
        flash("Пароли не совпадают")
        return redirect(url_for("auth_page", tab="register"))

    data["users"][username] = {"password": password, "team": None}
    save_data(data)

    session["user"] = username
    return redirect(url_for("team_page"))


@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    data = load_data()
    user_record = data["users"].get(username)

    if not user_record or user_record["password"] != password:
        flash("Неверный логин или пароль")
        return redirect(url_for("auth_page", tab="login"))

    session["user"] = username

    if user_record["team"]:
        return redirect(url_for("calendar_page"))
    return redirect(url_for("team_page"))


@app.route("/team")
def team_page():
    if not current_user():
        return redirect(url_for("landing"))
    return render_template("team.html")


@app.route("/team/join", methods=["POST"])
def team_join():
    team_name = request.form.get("team_name", "").strip()
    code = request.form.get("code", "").strip()

    if len(team_name) < 2:
        flash("Введите название команды")
        return redirect(url_for("team_page"))

    if len(code) != 7 or code[3] != "-" or not code.replace("-", "").isdigit():
        flash("Введите код в формате 123-456")
        return redirect(url_for("team_page"))

    data = load_data()
    username = current_user()
    data["users"][username]["team"] = team_name
    save_data(data)

    return redirect(url_for("calendar_page"))


@app.route("/logout/confirm")
def logout_confirm():
    return render_template("logout_confirm.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/calendar")
def calendar_page():
    username = current_user()
    if not username:
        return redirect(url_for("landing"))

    team = current_team()
    if not team:
        return redirect(url_for("team_page"))

    today = date.today()
    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))

    first_weekday, days_in_month = pycalendar.monthrange(year, month)

    data = load_data()
    team_events = data["events"].get(team, [])

    days = []
    for _ in range(first_weekday):
        days.append(None)

    for day_number in range(1, days_in_month + 1):
        day_date_str = "%04d-%02d-%02d" % (year, month, day_number)
        day_events = []
        for ev in team_events:
            if ev["date"] == day_date_str:
                ev["is_soon"] = is_event_soon(ev)
                ev["user_response"] = ev.get("responses", {}).get(username)
                day_events.append(ev)
        is_today = (year == today.year and month == today.month and day_number == today.day)
        days.append({"number": day_number, "events": day_events, "is_today": is_today})

    prev_month = month - 1
    prev_year = year
    if prev_month < 1:
        prev_month = 12
        prev_year -= 1

    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1

    dismissed = session.get("dismissed", [])
    notifications = []
    for ev in team_events:
        if not ev.get("time"):
            continue
        if ev["id"] in dismissed:
            continue
        if ev["created_by"] == username and not ev.get("notify_creator"):
            continue
        minutes_left = minutes_until(ev)
        if minutes_left is not None and 0 < minutes_left <= ev["notify_before"]:
            ev_year, ev_month, _ = ev["date"].split("-")
            notifications.append({
                "id": ev["id"],
                "title": ev["title"],
                "time": ev["time"],
                "year": int(ev_year),
                "month": int(ev_month)
            })

    return render_template(
        "calendar.html",
        month_name=MONTH_NAMES[month - 1],
        year=year,
        month=month,
        day_names=DAY_NAMES,
        days=days,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
        notifications=notifications
    )


@app.route("/notification/<event_id>/dismiss")
def dismiss_notification(event_id):
    dismissed = session.get("dismissed", [])
    if event_id not in dismissed:
        dismissed.append(event_id)
    session["dismissed"] = dismissed

    next_page = request.args.get("next") or url_for("calendar_page")
    return redirect(next_page)


@app.route("/event/new")
def event_new():
    username = current_user()
    if not username or not current_team():
        return redirect(url_for("landing"))

    picked_date = request.args.get("date", date.today().isoformat())
    return render_template("event_new.html", picked_date=picked_date)


@app.route("/event/add", methods=["POST"])
def event_add():
    username = current_user()
    team = current_team()
    if not username or not team:
        return redirect(url_for("landing"))

    title = request.form.get("title", "").strip()
    event_date = parse_date_ru(request.form.get("date", ""))
    event_time = normalize_time(request.form.get("time", ""))
    place = request.form.get("place", "").strip()
    desc = request.form.get("desc", "").strip()
    roles_raw = request.form.get("roles", "").strip()
    tags = request.form.getlist("tags")
    notify_before = int(request.form.get("notify_before", 30))
    notify_creator = request.form.get("notify_creator") == "on"

    if len(title) == 0 or len(event_date) == 0:
        flash("Заполните название и дату в формате ДД.ММ.ГГГГ")
        return redirect(url_for("event_new", date=event_date or date.today().isoformat()))

    if request.form.get("time", "").strip() and not event_time:
        flash("Введите время в формате ЧЧ:ММ, например 12:30")
        return redirect(url_for("event_new", date=event_date))

    roles = []
    if roles_raw:
        parts = roles_raw.split(",")
        for part in parts:
            clean = part.strip()
            if clean:
                roles.append(clean)

    data = load_data()
    if team not in data["events"]:
        data["events"][team] = []

    new_id = str(int(datetime.now().timestamp() * 1000))
    data["events"][team].append({
        "id": new_id,
        "title": title,
        "roles": roles,
        "date": event_date,
        "time": event_time,
        "place": place,
        "desc": desc,
        "tags": tags,
        "responses": {},
        "notify_before": notify_before,
        "notify_creator": notify_creator,
        "created_by": username
    })
    save_data(data)

    year, month, _ = event_date.split("-")
    return redirect(url_for("calendar_page", year=int(year), month=int(month)))


@app.route("/event/<event_id>")
def event_detail(event_id):
    team = current_team()
    if not team:
        return redirect(url_for("landing"))

    data = load_data()
    team_events = data["events"].get(team, [])
    found = None
    for ev in team_events:
        if ev["id"] == event_id:
            found = ev
            break

    if not found:
        return redirect(url_for("calendar_page"))

    response_options = ["Приду", "Возможно", "Не смогу"]
    user_response = found.get("responses", {}).get(current_user())
    return render_template(
        "event_detail.html",
        ev=found,
        response_options=response_options,
        user_response=user_response
    )


@app.route("/event/<event_id>/response", methods=["POST"])
def event_response(event_id):
    username = current_user()
    team = current_team()
    if not username or not team:
        return redirect(url_for("landing"))

    answer = request.form.get("answer", "")
    if answer not in ["Приду", "Возможно", "Не смогу"]:
        return redirect(url_for("event_detail", event_id=event_id))

    data = load_data()
    for ev in data["events"].get(team, []):
        if ev["id"] == event_id:
            ev.setdefault("responses", {})
            ev["responses"][username] = answer
            save_data(data)
            break

    return redirect(url_for("event_detail", event_id=event_id))


@app.route("/event/<event_id>/delete", methods=["POST"])
def event_delete(event_id):
    team = current_team()
    if not team:
        return redirect(url_for("landing"))

    data = load_data()
    team_events = data["events"].get(team, [])
    year = date.today().year
    month = date.today().month

    filtered = []
    for ev in team_events:
        if ev["id"] == event_id:
            y, m, _ = ev["date"].split("-")
            year, month = int(y), int(m)
        else:
            filtered.append(ev)

    data["events"][team] = filtered
    save_data(data)

    return redirect(url_for("calendar_page", year=year, month=month))


def minutes_until(ev):
    if not ev.get("time"):
        return None
    try:
        event_dt = datetime.strptime(ev["date"] + " " + ev["time"], "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    diff = event_dt - datetime.now()
    return diff.total_seconds() / 60


def is_event_soon(ev):
    minutes_left = minutes_until(ev)
    if minutes_left is None:
        return False
    return 0 < minutes_left <= 60


if __name__ == "__main__":
    app.run(debug=True)
