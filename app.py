import os
import csv
import io
from datetime import datetime, date
from collections import defaultdict
import json

from flask import Flask, render_template, redirect, url_for, flash, request, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user,
    login_required, logout_user, current_user
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate

from forms import (
    RegisterForm, LoginForm, TransactionForm,
    CategoryForm, BudgetForm, FilterForm
)
from collections import defaultdict
from datetime import datetime
# --------------------
# App setup
# --------------------
app = Flask(__name__)

# Use instance folder DB (works on most deployments)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(app.instance_path, "finance.db"))
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

db = SQLAlchemy(app)
migrate = Migrate(app, db)

login_manager = LoginManager(app)
login_manager.login_view = "login"

csrf = CSRFProtect(app)


# --------------------
# Models
# --------------------
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)

    # Sub-categories are just categories with a parent
    parent_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=True)
    parent = db.relationship("Category", remote_side=[id], backref=db.backref("children", lazy=True))

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref=db.backref("categories", lazy=True))

    def full_name(self) -> str:
        if self.parent:
            return f"{self.parent.name} / {self.name}"
        return self.name


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    transaction_type = db.Column(db.String(50), nullable=False)  # Income or Expense
    date = db.Column(db.DateTime, default=datetime.utcnow)

    description = db.Column(db.String(255), nullable=True)
    merchant = db.Column(db.String(255), nullable=True)

    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=True)
    category = db.relationship("Category", backref=db.backref("transactions", lazy=True))

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref=db.backref("transactions", lazy=True))


class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)

    month = db.Column(db.String(7), nullable=False)  # YYYY-MM
    warning_pct = db.Column(db.Float, default=0.8)   # 80% default

    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=True)
    category = db.relationship("Category", backref=db.backref("budgets", lazy=True))

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref=db.backref("budgets", lazy=True))


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def _ensure_sqlite_schema() -> None:
    """Lightweight schema safety for the shipped SQLite DB.
    - Adds missing columns when user upgrades without migrations.
    - Creates new tables if missing.
    """
    if not app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
        return

    # SQLAlchemy uses relative path for sqlite:///finance.db (in project root)
    db_path = app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "", 1)
    if not os.path.isabs(db_path):
        db_path = os.path.join(os.path.dirname(__file__), db_path)

    if not os.path.exists(db_path):
        return

    import sqlite3
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    def table_exists(name: str) -> bool:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
        return cur.fetchone() is not None

    def columns(table):
        cur.execute(f'PRAGMA table_info("{table}")')
        return {row[1] for row in cur.fetchall()}



    # Transaction table alterations
    if table_exists("transaction"):
        cols = columns("transaction")
        if "description" not in cols:
            cur.execute("ALTER TABLE transaction ADD COLUMN description VARCHAR(255)")
        if "merchant" not in cols:
            cur.execute("ALTER TABLE transaction ADD COLUMN merchant VARCHAR(255)")
        if "category_id" not in cols:
            cur.execute("ALTER TABLE transaction ADD COLUMN category_id INTEGER")

    # Budget table alterations
    if table_exists("budget"):
        cols = columns("budget")
        if "month" not in cols:
            cur.execute("ALTER TABLE budget ADD COLUMN month VARCHAR(7)")
            # backfill existing rows
            cur.execute("UPDATE budget SET month=? WHERE month IS NULL", (datetime.utcnow().strftime('%Y-%m'),))
        if "warning_pct" not in cols:
            cur.execute("ALTER TABLE budget ADD COLUMN warning_pct FLOAT")
            cur.execute("UPDATE budget SET warning_pct=0.8 WHERE warning_pct IS NULL")
        if "category_id" not in cols:
            cur.execute("ALTER TABLE budget ADD COLUMN category_id INTEGER")

    # Category table create if missing (no-op if exists)
    if not table_exists("category"):
        cur.execute(
            """CREATE TABLE category (
                id INTEGER PRIMARY KEY,
                name VARCHAR(120) NOT NULL,
                parent_id INTEGER,
                user_id INTEGER NOT NULL,
                FOREIGN KEY(parent_id) REFERENCES category(id),
                FOREIGN KEY(user_id) REFERENCES user(id)
            )"""
        )

    conn.commit()
    conn.close()


with app.app_context():
    db.create_all()
    _ensure_sqlite_schema()


# --------------------
# Helpers
# --------------------
def _month_str(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _category_options(user_id: int):
    # Top-level categories
    cats = Category.query.filter_by(user_id=user_id).order_by(Category.name.asc()).all()
    top = [c for c in cats if c.parent_id is None]
    subs = [c for c in cats if c.parent_id is not None]
    return top, subs, cats


def _category_map_for_js(cats):
    data = []
    for c in cats:
        data.append({
            "id": c.id,
            "name": c.name,
            "parent_id": c.parent_id,
            "full": c.full_name(),
        })
    return data


def _apply_filters(query, f: FilterForm):
    if f.transaction_type.data and f.transaction_type.data != "all":
        query = query.filter(Transaction.transaction_type == f.transaction_type.data)

    if f.category_id.data and f.category_id.data != "all":
        try:
            cid = int(f.category_id.data)
            query = query.filter(Transaction.category_id == cid)
        except ValueError:
            pass

    start = _parse_date(f.start_date.data)
    end = _parse_date(f.end_date.data)
    if start:
        query = query.filter(Transaction.date >= datetime.combine(start, datetime.min.time()))
    if end:
        query = query.filter(Transaction.date <= datetime.combine(end, datetime.max.time()))

    if f.search.data:
        s = f"%{f.search.data.strip()}%"
        query = query.filter(
            db.or_(
                Transaction.description.ilike(s),
                Transaction.merchant.ilike(s)
            )
        )
    return query


# --------------------
# Routes
# --------------------
@app.route("/", methods=["GET"])
@login_required
def index():
    tx_form = TransactionForm()
    cat_form = CategoryForm()
    budget_form = BudgetForm()
    filter_form = FilterForm(request.args)

    top, subs, cats = _category_options(current_user.id)

    # Populate selects
    tx_form.category_id.choices = [("", "(Optional) Select category")] + [(str(c.id), c.full_name()) for c in cats]
    cat_form.parent_id.choices = [("", "(No parent / Top-level)")] + [(str(c.id), c.name) for c in top]

    # Filter form choices
    filter_form.category_id.choices = [("all", "All categories")] + [(str(c.id), c.full_name()) for c in cats]

    # Budget choices (only top categories usually make sense, but allow any)
    budget_form.category_id.choices = [("", "(Optional) Select category")] + [(str(c.id), c.full_name()) for c in cats]

    tx_query = (
        Transaction.query
        .filter_by(user_id=current_user.id)
        .order_by(Transaction.date.desc())
    )
    tx_query = _apply_filters(tx_query, filter_form)
    transactions = tx_query.all()

    # Summary totals in filtered view
    total_income = sum(t.amount for t in transactions if t.transaction_type == "Income")
    total_expense = sum(t.amount for t in transactions if t.transaction_type == "Expense")
    net_balance = total_income - total_expense

    # Chart data (monthly totals + category breakdown)
    monthly = defaultdict(lambda: {"Income": 0.0, "Expense": 0.0})
    cat_breakdown = defaultdict(float)

    for t in transactions:
        key = _month_str(t.date.date())
        monthly[key][t.transaction_type] += float(t.amount or 0)

    if t.transaction_type == "Expense":
        if t.category:
            cat_breakdown[t.category.full_name()] += float(t.amount or 0)
        else:
            cat_breakdown["Uncategorized"] += float(t.amount or 0)


    # sort months
    months = sorted(monthly.keys())
    income_series = [round(monthly[m]["Income"], 2) for m in months]
    expense_series = [round(monthly[m]["Expense"], 2) for m in months]

    # budgets + alerts for current month (on full month, not just filtered list)
    current_month = datetime.utcnow().strftime("%Y-%m")
    budgets = Budget.query.filter_by(user_id=current_user.id, month=current_month).all()

    # compute spending by category for month
    month_start = datetime.strptime(current_month + "-01", "%Y-%m-%d")
    month_tx = Transaction.query.filter_by(user_id=current_user.id).filter(
        Transaction.transaction_type == "Expense",
        Transaction.date >= month_start
    ).all()

    month_spend_by_cat = defaultdict(float)
    for t in month_tx:
        if t.category:
            month_spend_by_cat[t.category_id] += float(t.amount or 0)

    budget_status = []
    for b in budgets:
        spent = month_spend_by_cat.get(b.category_id, 0.0) if b.category_id else 0.0
        used_pct = (spent / b.amount) if b.amount else 0.0
        budget_status.append({
            "id": b.id,
            "month": b.month,
            "amount": round(b.amount, 2),
            "warning_pct": b.warning_pct,
            "category": b.category.full_name() if b.category else "(No category)",
            "spent": round(spent, 2),
            "remaining": round(b.amount - spent, 2),
            "used_pct": round(used_pct * 100, 1),
            "is_warning": used_pct >= (b.warning_pct or 0.8) and used_pct < 1.0,
            "is_over": used_pct >= 1.0,
        })

    # Flash budget alerts once per request (based on current month)
    for s in budget_status:
        if s["is_over"]:
            flash(f"Budget exceeded: {s['category']} — spent ${s['spent']:.2f} of ${s['amount']:.2f}", "danger")
        elif s["is_warning"]:
            flash(f"Budget warning: {s['category']} — {s['used_pct']:.1f}% used", "warning")

    return render_template(
        "index.html",
        tx_form=tx_form,
        cat_form=cat_form,
        budget_form=budget_form,
        filter_form=filter_form,
        transactions=transactions,
        total_income=round(total_income, 2),
        total_expense=round(total_expense, 2),
        net_balance=round(net_balance, 2),
        months=months,
        income_series=income_series,
        expense_series=expense_series,
        cat_labels=list(cat_breakdown.keys()),
        cat_values=[round(v, 2) for v in cat_breakdown.values()],
        categories_json=json.dumps(_category_map_for_js(cats)),
        budget_status=budget_status,
        current_month=current_month,
    )


@app.route("/transaction", methods=["POST"])
@login_required
def transaction():
    form = TransactionForm()
    top, subs, cats = _category_options(current_user.id)
    form.category_id.choices = [("", "(Optional) Select category")] + [(str(c.id), c.full_name()) for c in cats]

    if form.validate_on_submit():
        selected_category = None
        if form.category_id.data:
            try:
                selected_category = Category.query.filter_by(
                    id=int(form.category_id.data),
                    user_id=current_user.id
                ).first()
            except ValueError:
                selected_category = None

        tx_date = form.date.data or date.today()
        t = Transaction(
            amount=form.amount.data,
            transaction_type=form.transaction_type.data,
            date=datetime.combine(tx_date, datetime.min.time()),
            description=form.description.data.strip() if form.description.data else None,
            merchant=form.merchant.data.strip() if form.merchant.data else None,
            category_id=selected_category.id if selected_category else None,
            user_id=current_user.id,
        )

        db.session.add(t)
        db.session.commit()
        flash("Transaction added.", "success")
    else:
        flash("Please fix the errors in the transaction form.", "danger")

    return redirect(url_for("index"))


@app.route("/transaction/<int:tx_id>/delete", methods=["POST"])
@login_required
def delete_transaction(tx_id):
    transaction = Transaction.query.filter_by(id=tx_id, user_id=current_user.id).first_or_404()
    db.session.delete(transaction)
    db.session.commit()
    flash("Transaction deleted.", "success")
    return redirect(url_for("index"))


@app.route("/category", methods=["POST"])
@login_required
def add_category():
    form = CategoryForm()
    top, subs, cats = _category_options(current_user.id)
    form.parent_id.choices = [("", "(No parent / Top-level)")] + [(str(c.id), c.name) for c in top]

    if form.validate_on_submit():
        name = form.name.data.strip()
        parent = None
        if form.parent_id.data:
            try:
                parent = Category.query.filter_by(id=int(form.parent_id.data), user_id=current_user.id).first()
            except ValueError:
                parent = None

        new_cat = Category(name=name, parent_id=parent.id if parent else None, user_id=current_user.id)
        db.session.add(new_cat)
        db.session.commit()
        flash("Category saved.", "success")
    else:
        flash("Please fix the errors in the category form.", "danger")

    return redirect(url_for("index"))


@app.route("/budget", methods=["POST"])
@login_required
def set_budget():
    form = BudgetForm()
    top, subs, cats = _category_options(current_user.id)
    form.category_id.choices = [("", "(Optional) Select category")] + [(str(c.id), c.full_name()) for c in cats]

    if form.validate_on_submit():
        month = form.month.data.strip()
        # Validate YYYY-MM
        try:
            datetime.strptime(month + "-01", "%Y-%m-%d")
        except ValueError:
            flash("Invalid month format. Use YYYY-MM.", "danger")
            return redirect(url_for("index"))

        cat_id = None
        if form.category_id.data:
            try:
                cat = Category.query.filter_by(id=int(form.category_id.data), user_id=current_user.id).first()
                cat_id = cat.id if cat else None
            except ValueError:
                cat_id = None

        # Upsert per (user, month, category)
        existing = Budget.query.filter_by(user_id=current_user.id, month=month, category_id=cat_id).first()
        if existing:
            existing.amount = form.amount.data
            existing.warning_pct = form.warning_pct.data
        else:
            b = Budget(
                amount=form.amount.data,
                month=month,
                warning_pct=form.warning_pct.data,
                category_id=cat_id,
                user_id=current_user.id,
            )
            db.session.add(b)

        db.session.commit()
        flash("Budget saved.", "success")
    else:
        flash("Please fix the errors in the budget form.", "danger")

    return redirect(url_for("index"))


@app.route("/export/csv", methods=["GET"])
@login_required
def export_csv():
    # Reuse filters from query string
    filter_form = FilterForm(request.args)
    top, subs, cats = _category_options(current_user.id)
    filter_form.category_id.choices = [("all", "All categories")] + [(str(c.id), c.full_name()) for c in cats]

    tx_query = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.date.desc())
    tx_query = _apply_filters(tx_query, filter_form)
    rows = tx_query.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Type", "Amount", "Category", "Merchant", "Description"])
    for t in rows:
        writer.writerow([
            t.date.strftime("%Y-%m-%d"),
            t.transaction_type,
            f"{t.amount:.2f}",
            t.category.full_name() if t.category else "",
            t.merchant or "",
            t.description or "",
        ])

    mem = io.BytesIO()
    mem.write(output.getvalue().encode("utf-8"))
    mem.seek(0)

    filename = f"transactions_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name=filename)


@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()

        if user and user.check_password(form.password.data):
            login_user(user)
            return redirect(url_for("index"))

        flash("Login failed. Check your credentials.", "danger")

    return render_template("login.html", form=form)


@app.route("/register", methods=["GET", "POST"])
def register():
    form = RegisterForm()

    if form.validate_on_submit():
        existing = User.query.filter_by(username=form.username.data).first()

        if existing:
            flash("Username already exists.", "danger")
        else:
            new_user = User(username=form.username.data)
            new_user.set_password(form.password.data)

            db.session.add(new_user)
            db.session.commit()

            flash("Account created successfully! Please log in.", "success")
            return redirect(url_for("login"))

    return render_template("register.html", form=form)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)
