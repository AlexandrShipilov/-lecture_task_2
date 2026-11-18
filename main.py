"""
=====================================================================
 БИЗНЕС-ТРЕКЕР РАСХОДОВ И ДОХОДОВ (Kivy) — лекция 6 + домашнее задание
=====================================================================
"""

import csv
import io
import json
import os
import threading
import urllib.request
import urllib.error
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.properties import NumericProperty, StringProperty, BooleanProperty, ListProperty
from kivy.uix.image import Image
from kivy.core.image import Image as CoreImage
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.storage.jsonstore import JsonStore

# ---------------------------------------------------------------------
# ДЗ, п.1: графики Matplotlib внутри Kivy
# ---------------------------------------------------------------------
MATPLOTLIB_AVAILABLE = False
FigureCanvasKivyAgg = None
try:
    import matplotlib
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except Exception:
    MATPLOTLIB_AVAILABLE = False

if MATPLOTLIB_AVAILABLE:
    try:
        from kivy_garden.matplotlib.backend_kivyagg import FigureCanvasKivyAgg
    except Exception:
        try:
            from kivy.garden.matplotlib.backend_kivyagg import FigureCanvasKivyAgg
        except Exception:
            FigureCanvasKivyAgg = None

# ---------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------
DATA_FILE = 'transactions.json'      # локальное хранилище (JsonStore)
EXPORT_FILE = 'transactions_export.csv'

# ДЗ, п.2: адрес облачного REST API.
# Вариант A — собственный сервер:  http://myserver.ru:5000
# Вариант B — Firebase Realtime DB: https://<проект>-default-rtdb.firebaseio.com
SERVER_URL = os.environ.get('TRACKER_SERVER_URL', 'https://example.com')
SYNC_PATH = '/transactions.json'     # для Firebase путь уже содержит .json

EXPENSE_CATEGORIES = ['Офис', 'Зарплаты', 'Маркетинг', 'Логистика', 'Налоги', 'Прочее']
INCOME_CATEGORIES = ['Продажи', 'Услуги', 'Инвестиции', 'Прочее']

# ---------------------------------------------------------------------
# ДЗ, п.2: клиент синхронизации с облаком (REST API)
# ---------------------------------------------------------------------
class CloudSync:
    """Отправка/получение данных на облачный сервер через REST API.

    Протокол: PUT  {SERVER_URL}{SYNC_PATH}  -> загрузка локальных записей
              GET  {SERVER_URL}{SYNC_PATH}  -> скачивание облачных записей
    Формат: {"ключ": {"type", "category", "description", "amount", "date"}}
    Совместимо с Firebase Realtime Database REST API из коробки.
    """

    def __init__(self, server_url, path=SYNC_PATH, timeout=10):
        self.server_url = server_url.rstrip('/')
        self.path = path
        self.timeout = timeout

    def _request(self, method, payload=None):
        url = self.server_url + self.path
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header('Content-Type', 'application/json; charset=utf-8')
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = response.read().decode('utf-8')
            return json.loads(body) if body else {}

    def push(self, records):
        """Загрузить локальные записи в облако (перезаписать узел)."""
        self._request('PUT', {'records': records})
        return True

    def pull(self):
        """Скачать записи из облака."""
        data = self._request('GET')
        return data.get('records', data) if isinstance(data, dict) else {}

# ---------------------------------------------------------------------
# Описание интерфейса на языке KV (разделение логики и представления)
# ---------------------------------------------------------------------
Builder.load_string('''
#:import dp kivy.metrics.dp

# ---------- Строка списка операций ----------
<TransactionRow>:
    canvas.before:
        Color:
            rgba: (0.9, 0.9, 0.9, 1) if self.selected else (1, 1, 1, 1)
        Rectangle:
            pos: self.pos
            size: self.size
    orientation: 'horizontal'
    padding: 10
    spacing: 5
    height: dp(50)

    Label:
        text: root.category
        size_hint_x: 0.25
        color: 0.2, 0.2, 0.2, 1
    Label:
        text: root.description
        size_hint_x: 0.35
        color: 0.2, 0.2, 0.2, 1
    Label:
        text: ('- ' if root.ttype == 'expense' else '+ ') + str(root.amount) + ' руб.'
        size_hint_x: 0.22
        bold: True
        color: (0.9, 0.1, 0.1, 1) if root.ttype == 'expense' else (0.1, 0.6, 0.1, 1)
    Label:
        text: root.date[:10]
        size_hint_x: 0.18
        color: 0.5, 0.5, 0.5, 1

# ---------- Оптимизированный список ----------
<TransactionsRV>:
    viewclass: 'TransactionRow'
    RecycleBoxLayout:
        default_size: None, dp(50)
        default_size_hint: 1, None
        size_hint_y: None
        height: self.minimum_height
        orientation: 'vertical'

# ---------- Главный экран ----------
<MainScreen>:
    BoxLayout:
        orientation: 'vertical'
        padding: 20
        spacing: 10

        Label:
            text: 'БИЗНЕС-ТРЕКЕР: РАСХОДЫ И ДОХОДЫ'
            font_size: 22
            bold: True
            color: 0.2, 0.4, 0.8, 1
            size_hint_y: 0.10

        GridLayout:
            cols: 3
            spacing: 10
            size_hint_y: 0.16

            Button:
                text: 'Добавить\\nрасход'
                on_press: root.show_add_popup('expense')
                background_color: 0.8, 0.2, 0.2, 1
            Button:
                text: 'Добавить\\nдоход'
                on_press: root.show_add_popup('income')
                background_color: 0.2, 0.6, 0.2, 1
            Button:
                text: 'Аналитика\\n(графики)'
                on_press: root.open_analytics()
                background_color: 0.3, 0.3, 0.7, 1
            Button:
                text: 'Экспорт CSV'
                on_press: root.export_data()
                background_color: 0.7, 0.5, 0.2, 1
            Button:
                text: 'Синхронизация\\nс облаком'
                on_press: root.sync_with_cloud()
                background_color: 0.2, 0.5, 0.7, 1
            Label:
                text: root.sync_status
                font_size: 12
                color: 0.4, 0.4, 0.4, 1

        BoxLayout:
            orientation: 'horizontal'
            size_hint_y: 0.09
            Label:
                text: 'Доходы: ' + str(root.total_incomes) + ' руб.'
                color: 0.1, 0.6, 0.1, 1
                bold: True
            Label:
                text: 'Расходы: ' + str(root.total_expenses) + ' руб.'
                color: 0.9, 0.1, 0.1, 1
                bold: True
            Label:
                text: 'БАЛАНС: ' + str(root.balance) + ' руб.'
                color: 0.2, 0.4, 0.8, 1
                bold: True
                font_size: 16

        TransactionsRV:
            id: rv
            size_hint_y: 0.65

# ---------- Экран аналитики с графиками ----------
<AnalyticsScreen>:
    BoxLayout:
        orientation: 'vertical'
        padding: 15
        spacing: 10

        Label:
            text: 'АНАЛИТИКА (ГРАФИКИ)'
            font_size: 20
            bold: True
            color: 0.2, 0.4, 0.8, 1
            size_hint_y: 0.10

        BoxLayout:
            id: graph_container
            orientation: 'vertical'
            size_hint_y: 0.80

        Button:
            text: 'Назад'
            size_hint_y: 0.10
            on_press: root.go_back()

# ---------- Всплывающее окно добавления операции ----------
<AddTransactionPopup>:
    size_hint: 0.85, 0.75
    title: root.popup_title
    auto_dismiss: False

    BoxLayout:
        orientation: 'vertical'
        padding: 20
        spacing: 10

        Label:
            text: 'Категория:'
            size_hint_y: 0.12
        Spinner:
            id: category_spinner
            text: 'Выберите категорию'
            values: root.category_values
            size_hint_y: 0.15

        Label:
            text: 'Описание:'
            size_hint_y: 0.12
        TextInput:
            id: description_input
            multiline: False
            size_hint_y: 0.15

        Label:
            text: 'Сумма (руб.):'
            size_hint_y: 0.12
        TextInput:
            id: amount_input
            multiline: False
            input_filter: 'float'
            size_hint_y: 0.15

        BoxLayout:
            orientation: 'horizontal'
            spacing: 10
            size_hint_y: 0.19
            Button:
                text: 'Отмена'
                on_press: root.dismiss()
                background_color: 0.8, 0.2, 0.2, 1
            Button:
                text: 'Сохранить'
                on_press: root.save_transaction()
                background_color: 0.2, 0.6, 0.2, 1
''')

# ---------------------------------------------------------------------
# Модель данных и бизнес-логика
# ---------------------------------------------------------------------
class TransactionRow(RecycleDataViewBehavior, BoxLayout):
    """Модель строки операции для RecycleView."""

    ttype = StringProperty('expense')
    category = StringProperty('')
    description = StringProperty('')
    amount = NumericProperty(0)
    date = StringProperty('')
    selected = BooleanProperty(False)

    def refresh_view_attrs(self, rv, index, data):
        self.index = index
        return super().refresh_view_attrs(rv, index, data)

class TransactionsRV(RecycleView):
    """Виджет для отображения списка операций."""
    pass

class MainScreen(Screen):
    """Главный экран приложения."""

    total_expenses = NumericProperty(0)
    total_incomes = NumericProperty(0)
    balance = NumericProperty(0)
    sync_status = StringProperty('Синхронизация не выполнялась')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.store = JsonStore(DATA_FILE)
        # ids виджетов доступны только после применения KV-правила,
        # поэтому загрузку данных откладываем на следующий кадр
        Clock.schedule_once(lambda dt: self.load_data())

    # ---------- Загрузка / пересчёт ----------
    def load_data(self):
        """Загрузка операций из локального хранилища и пересчёт итогов."""
        transactions = []
        total_exp = 0.0
        total_inc = 0.0
        for key in self.store.keys():
            tx = self.store.get(key)
            amount = float(tx.get('amount', 0))
            ttype = tx.get('type', 'expense')
            transactions.append({
                'key': key,
                'ttype': ttype,
                'category': tx.get('category', ''),
                'description': tx.get('description', ''),
                'amount': amount,
                'date': tx.get('date', ''),
            })
            if ttype == 'expense':
                total_exp += amount
            else:
                total_inc += amount
        # новые операции — сверху
        transactions.sort(key=lambda t: t['date'], reverse=True)
        self.ids.rv.data = transactions
        self.total_expenses = round(total_exp, 2)
        self.total_incomes = round(total_inc, 2)
        # ДЗ, п.3: баланс = доходы - расходы
        self.balance = round(total_inc - total_exp, 2)

    def all_records(self):
        """Все записи хранилища в виде обычного словаря (для облака/CSV)."""
        return {key: self.store.get(key) for key in self.store.keys()}

    # ---------- CRUD ----------
    def show_add_popup(self, ttype):
        """Показать попап добавления расхода или дохода."""
        popup = AddTransactionPopup(main_screen=self, ttype=ttype)
        popup.open()

    def add_transaction(self, ttype, category, description, amount):
        """Добавление новой операции (бизнес-логика)."""
        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except (ValueError, TypeError):
            self.show_error_popup('Ошибка', 'Сумма должна быть положительным числом')
            return False

        transaction = {
            'type': ttype,
            'category': category,
            'description': description,
            'amount': amount,
            'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        key = f"tx_{datetime.now().timestamp()}"
        self.store.put(key, **transaction)
        self.load_data()
        return True

    # ---------- Аналитика ----------
    def open_analytics(self):
        """Переход на экран аналитики с графиками."""
        self.manager.current = 'analytics'

    def totals_by_category(self, ttype):
        """Суммы по категориям для заданного типа операции."""
        result = {}
        for tx in self.all_records().values():
            if tx.get('type') == ttype:
                cat = tx.get('category', 'Прочее')
                result[cat] = round(result.get(cat, 0) + float(tx.get('amount', 0)), 2)
        return result

    # ---------- Экспорт в CSV (базовая функция лекции) ----------
    def export_data(self):
        """Экспорт всех операций в CSV-файл."""
        try:
            with open(EXPORT_FILE, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow(['Тип', 'Категория', 'Описание', 'Сумма', 'Дата'])
                for tx in self.all_records().values():
                    writer.writerow([
                        'Расход' if tx.get('type') == 'expense' else 'Доход',
                        tx.get('category', ''),
                        tx.get('description', ''),
                        tx.get('amount', 0),
                        tx.get('date', ''),
                    ])
            self.show_error_popup('Успех', f'Данные экспортированы в файл\n{EXPORT_FILE}')
        except Exception as e:
            self.show_error_popup('Ошибка экспорта', str(e))

    # ---------- ДЗ, п.2: синхронизация с облаком ----------
    def sync_with_cloud(self):
        """Отправка локальных данных в облако и слияние с облачными.

        Выполняется в фоновом потоке, чтобы не блокировать интерфейс.
        """
        if SERVER_URL.startswith('https://example.com'):
            self.sync_status = 'Задайте SERVER_URL в коде или переменной TRACKER_SERVER_URL'
            self.show_error_popup(
                'Синхронизация',
                'Не задан адрес облачного сервера.\n'
                'Укажите SERVER_URL в начале файла main.py\n'
                '(например, Firebase Realtime Database).')
            return

        self.sync_status = 'Синхронизация…'
        thread = threading.Thread(target=self._sync_worker, daemon=True)
        thread.start()

    def _sync_worker(self):
        """Фоновая работа с сетью (не трогает UI напрямую)."""
        try:
            client = CloudSync(SERVER_URL, SYNC_PATH)
            local = self.all_records()
            remote = client.pull()                  # 1. скачали облачные записи
            merged = self._merge_records(local, remote)
            client.push(merged)                     # 2. выгрузили объединённый набор
            Clock.schedule_once(lambda dt: self._apply_merge(merged))
        except (urllib.error.URLError, OSError, ValueError) as e:
            Clock.schedule_once(
                lambda dt: self._sync_failed(str(e)))

    @staticmethod
    def _merge_records(local, remote):
        """Слияние записей: при конфликте побеждает более свежая дата."""
        merged = dict(remote)
        for key, record in local.items():
            if key not in merged:
                merged[key] = record
            else:
                local_date = record.get('date', '')
                remote_date = merged[key].get('date', '')
                if local_date >= remote_date:
                    merged[key] = record
        return merged

    def _apply_merge(self, merged):
        """Применение результата слияния (вызывается в главном потоке)."""
        self.store.clear()
        for key, record in merged.items():
            self.store.put(key, **record)
        self.load_data()
        self.sync_status = f'Синхронизировано: {len(merged)} записей'
        self.show_error_popup('Синхронизация', f'Успешно!\nЗаписей в облаке и локально: {len(merged)}')

    def _sync_failed(self, error_text):
        self.sync_status = 'Ошибка синхронизации (сервер недоступен?)'
        self.show_error_popup('Ошибка синхронизации', error_text)

    # ---------- Служебное ----------
    def show_error_popup(self, title, message):
        """Утилита для показа всплывающих окон."""
        popup = Popup(
            title=title,
            content=Label(text=message),
            size_hint=(0.7, 0.35),
        )
        popup.open()

class AddTransactionPopup(Popup):
    """Попап добавления расхода или дохода."""

    popup_title = StringProperty('Добавить операцию')
    category_values = ListProperty([])

    def __init__(self, main_screen, ttype='expense', **kwargs):
        super().__init__(**kwargs)
        self.main_screen = main_screen
        self.ttype = ttype
        if ttype == 'expense':
            self.popup_title = 'Добавить новый расход'
            self.category_values = list(EXPENSE_CATEGORIES)
        else:
            self.popup_title = 'Добавить новый доход'
            self.category_values = list(INCOME_CATEGORIES)
        # дублируем в сам Spinner на случай, если привязка KV ещё не сработала
        self.ids.category_spinner.values = self.category_values

    def save_transaction(self):
        """Сохранение операции с проверкой ввода."""
        category = self.ids.category_spinner.text
        description = self.ids.description_input.text.strip()
        amount = self.ids.amount_input.text.strip()

        if category == 'Выберите категорию':
            self.main_screen.show_error_popup('Ошибка', 'Выберите категорию')
            return
        if not description:
            self.main_screen.show_error_popup('Ошибка', 'Введите описание')
            return
        if not amount:
            self.main_screen.show_error_popup('Ошибка', 'Введите сумму')
            return

        if self.main_screen.add_transaction(self.ttype, category, description, amount):
            self.dismiss()

# ---------------------------------------------------------------------
# ДЗ, п.1: экран аналитики с графиками Matplotlib
# ---------------------------------------------------------------------
class AnalyticsScreen(Screen):
    """Экран с графиками: структура расходов и доходы vs расходы."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._canvases = []

    def on_enter(self):
        """Экран открылся — строим графики."""
        self.build_charts()

    def build_charts(self):
        """Построение диаграмм по данным главного экрана."""
        container = self.ids.graph_container
        self._clear_charts(container)

        main = self.manager.get_screen('main')
        expenses = main.totals_by_category('expense')
        incomes = main.totals_by_category('income')

        if not MATPLOTLIB_AVAILABLE:
            container.add_widget(Label(
                text='Matplotlib не установлен.\n'
                     'Выполните: py -m pip install matplotlib',
                color=(0.9, 0.1, 0.1, 1)))
            return

        if not expenses and not incomes:
            container.add_widget(Label(text='Нет данных для аналитики'))
            return

        try:
            # --- Круговая диаграмма: расходы по категориям ---
            if expenses:
                fig1 = plt.figure(figsize=(5, 3.2))
                plt.pie(
                    list(expenses.values()),
                    labels=list(expenses.keys()),
                    autopct='%1.1f%%',
                    startangle=90,
                    textprops={'fontsize': 10},
                )
                plt.title('Структура расходов по категориям')
                self._add_figure(container, fig1)

            # --- Столбчатая диаграмма: доходы vs расходы ---
            fig2 = plt.figure(figsize=(5, 2.6))
            categories = sorted(set(expenses) | set(incomes))
            x = range(len(categories))
            width = 0.38
            plt.bar(
                [i - width / 2 for i in x],
                [incomes.get(c, 0) for c in categories],
                width, label='Доходы', color='seagreen',
            )
            plt.bar(
                [i + width / 2 for i in x],
                [expenses.get(c, 0) for c in categories],
                width, label='Расходы', color='indianred',
            )
            plt.xticks(list(x), categories, fontsize=9)
            plt.ylabel('руб.')
            plt.title('Доходы и расходы по категориям')
            plt.legend(fontsize=9)
            plt.tight_layout()
            self._add_figure(container, fig2)
        except Exception as e:
            container.add_widget(Label(text=f'Ошибка построения графиков:\n{e}'))

    def _add_figure(self, container, fig):
        """Показ фигуры matplotlib: «живой» холст Kivy Garden, а если
        garden не установлен — PNG в памяти как обычное изображение."""
        if FigureCanvasKivyAgg is not None:
            try:
                canvas = FigureCanvasKivyAgg(fig)
                container.add_widget(canvas)
                self._canvases.append(canvas)
                return
            except Exception:
                plt.close(fig)
        # --- Фолбэк без Kivy Garden: фигура -> PNG -> Image ---
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=110)
        plt.close(fig)
        buf.seek(0)
        texture = CoreImage(buf, ext='png').texture
        image = Image(
            texture=texture,
            allow_stretch=True,
            keep_ratio=True,
        )
        container.add_widget(image)
        self._canvases.append(image)

    def _clear_charts(self, container):
        """Удаление ВСЕХ старых графиков (холстов и картинок) и фигур."""
        for widget in list(container.children):
            container.remove_widget(widget)
        self._canvases = []
        if MATPLOTLIB_AVAILABLE:
            plt.close('all')

    def go_back(self):
        """Возврат на главный экран."""
        self.manager.current = 'main'

# ---------------------------------------------------------------------
# Основное приложение
# ---------------------------------------------------------------------
class ExpenseTrackerApp(App):
    """Основной класс приложения."""

    def build(self):
        """Сборка интерфейса приложения."""
        self.title = 'Business Expense Tracker'
        sm = ScreenManager()
        sm.add_widget(MainScreen(name='main'))
        sm.add_widget(AnalyticsScreen(name='analytics'))
        return sm

    def on_pause(self):
        """Обработка паузы (важно для Android/iOS)."""
        return True

    def on_resume(self):
        """Обработка возврата из паузы."""
        pass

# --- Точка входа ---
if __name__ == '__main__':
    ExpenseTrackerApp().run()