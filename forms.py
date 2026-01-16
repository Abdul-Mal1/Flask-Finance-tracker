from flask_wtf import FlaskForm
from wtforms import (
    StringField, PasswordField, SubmitField, FloatField,
    SelectField
)
from wtforms.fields import DateField
from wtforms.validators import DataRequired, Length, EqualTo, NumberRange, Optional, Regexp


class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=100)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Sign Up')


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')


class TransactionForm(FlaskForm):
    amount = FloatField('Amount', validators=[DataRequired(), NumberRange(min=0.01)])
    transaction_type = SelectField(
        'Type',
        choices=[('Income', 'Income'), ('Expense', 'Expense')],
        validators=[DataRequired()],
    )
    date = DateField('Date', validators=[Optional()], format="%Y-%m-%d")
    category_id = SelectField('Category', choices=[("", "(Optional) Select category")], validators=[Optional()])
    merchant = StringField('Merchant', validators=[Optional(), Length(max=255)])
    description = StringField('Description / Notes', validators=[Optional(), Length(max=255)])
    submit = SubmitField('Add Transaction')


class CategoryForm(FlaskForm):
    name = StringField('Category name', validators=[DataRequired(), Length(min=2, max=120)])
    parent_id = SelectField('Parent category', choices=[("", "(No parent / Top-level)")], validators=[Optional()])
    submit = SubmitField('Save Category')


class BudgetForm(FlaskForm):
    month = StringField('Month (YYYY-MM)', validators=[DataRequired(), Regexp(r"^\d{4}-\d{2}$", message="Use YYYY-MM")])
    category_id = SelectField('Category', choices=[("", "(Optional) Select category")], validators=[Optional()])
    amount = FloatField('Budget amount', validators=[DataRequired(), NumberRange(min=0.01)])
    warning_pct = FloatField('Warning threshold (e.g., 0.8)', validators=[DataRequired(), NumberRange(min=0.1, max=1.0)])
    submit = SubmitField('Save Budget')


class FilterForm(FlaskForm):
    transaction_type = SelectField(
        'Type',
        choices=[('all', 'All'), ('Income', 'Income'), ('Expense', 'Expense')],
        validators=[Optional()],
    )
    category_id = SelectField('Category', choices=[('all', 'All categories')], validators=[Optional()])
    start_date = StringField('Start date', validators=[Optional()])  # YYYY-MM-DD
    end_date = StringField('End date', validators=[Optional()])      # YYYY-MM-DD
    search = StringField('Search', validators=[Optional(), Length(max=120)])
    submit = SubmitField('Apply')
