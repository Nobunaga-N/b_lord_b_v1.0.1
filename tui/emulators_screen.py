"""
Экран управления эмуляторами
"""

from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from loguru import logger

from tui.base_screen import BaseScreen


class EmulatorsScreen(BaseScreen):
    """Экран управления эмуляторами"""

    def __init__(self, app):
        super().__init__(app)
        self.selected_index = 0
        self.emulators_list = []

    def activate(self):
        """При активации загружаем список эмуляторов"""
        self._load_emulators()

    def _load_emulators(self):
        """Загрузка списка эмуляторов"""
        emulators = self.app.orchestrator.get_emulators_list()
        # Преобразуем в список для навигации
        self.emulators_list = [(idx, emu) for idx, emu in sorted(emulators.items())]
        if self.selected_index >= len(self.emulators_list):
            self.selected_index = max(0, len(self.emulators_list) - 1)

    def render(self) -> Layout:
        """Отрисовка экрана эмуляторов"""
        layout = Layout()

        # Заголовок
        title_panel = Panel(
            Text("Управление эмуляторами", justify="center", style="bold cyan"),
            style="cyan"
        )

        # Таблица эмуляторов
        emulators_table = Table(show_header=True, box=None)
        emulators_table.add_column("", width=3)
        emulators_table.add_column("ID", style="cyan", width=5)
        emulators_table.add_column("Имя", style="white")
        emulators_table.add_column("Порт", style="yellow", width=8)
        emulators_table.add_column("Активен", style="green", width=10)
        emulators_table.add_column("Заметки", style="dim")

        if not self.emulators_list:
            info_text = Text()
            info_text.append("⚠️  Эмуляторы не найдены\n\n", style="bold yellow")
            info_text.append("Нажмите [S] для сканирования", style="cyan")

            emulators_panel = Panel(
                info_text,
                title="[cyan]Список эмуляторов[/cyan]",
                border_style="cyan"
            )
        else:
            for i, (idx, emu) in enumerate(self.emulators_list):
                # Маркер выбранного элемента
                marker = "►" if i == self.selected_index else " "

                # Порт ADB
                adb_port = 5554 + idx * 2

                # Статус активности
                status_icon = "✓" if emu.enabled else "✗"
                status_style = "green" if emu.enabled else "red"

                # Заметки
                notes = emu.notes if hasattr(emu, 'notes') and emu.notes else "-"

                # Подсветка выбранной строки
                row_style = "bold" if i == self.selected_index else ""

                emulators_table.add_row(
                    marker,
                    str(idx),
                    emu.name,
                    str(adb_port),
                    f"[{status_style}]{status_icon}[/{status_style}]",
                    notes,
                    style=row_style
                )

            # Информация
            info_text = Text()
            info_text.append(f"Всего: {len(self.emulators_list)} эмуляторов\n")
            enabled_count = sum(1 for _, emu in self.emulators_list if emu.enabled)
            info_text.append(f"Активных: {enabled_count}\n")

            emulators_panel = Panel(
                emulators_table,
                title=f"[cyan]Список эмуляторов[/cyan]",
                subtitle=info_text,
                border_style="cyan"
            )

        # Панель помощи
        help_table = Table(show_header=False, box=None, padding=(0, 2))
        help_table.add_column("Key", style="cyan bold", width=12)
        help_table.add_column("Action", style="white")

        help_table.add_row("[↑/↓]", "Навигация")
        help_table.add_row("[SPACE]", "Переключить вкл/выкл")
        help_table.add_row("[A]", "Все вкл/выкл")
        help_table.add_row("[S]", "Сканировать")
        help_table.add_row("[ESC]", "Назад")

        help_panel = Panel(
            help_table,
            title="[cyan]Управление[/cyan]",
            border_style="cyan"
        )

        # Компоновка
        layout.split_column(
            Layout(title_panel, size=3),
            Layout(emulators_panel),
            Layout(help_panel, size=8)
        )

        return layout

    def handle_key(self, key: str) -> bool:
        """Обработка нажатий клавиш"""
        key = key.lower()

        if key == 'escape':
            self.app.switch_screen('main')
            return True

        if not self.emulators_list:
            if key == 's':
                # Сканирование эмуляторов
                logger.info("Запуск сканирования эмуляторов...")
                if self.app.orchestrator.scan_emulators():
                    self._load_emulators()
                    return True
            return False

        if key == 'up':
            self.selected_index = max(0, self.selected_index - 1)
            return True
        elif key == 'down':
            self.selected_index = min(len(self.emulators_list) - 1, self.selected_index + 1)
            return True
        elif key == ' ':  # Пробел - переключить выбранный
            if 0 <= self.selected_index < len(self.emulators_list):
                idx, emu = self.emulators_list[self.selected_index]
                if emu.enabled:
                    self.app.orchestrator.disable_emulator(idx)
                else:
                    self.app.orchestrator.enable_emulator(idx)
                self._load_emulators()
                return True
        elif key == 'a':  # Все вкл/выкл
            # Определяем, что делать: если все включены - выключить, иначе включить
            all_enabled = all(emu.enabled for _, emu in self.emulators_list)
            for idx, emu in self.emulators_list:
                if all_enabled:
                    self.app.orchestrator.disable_emulator(idx)
                else:
                    self.app.orchestrator.enable_emulator(idx)
            self._load_emulators()
            return True
        elif key == 's':
            # Сканирование эмуляторов
            logger.info("Запуск сканирования эмуляторов...")
            if self.app.orchestrator.scan_emulators():
                self._load_emulators()
                return True

        return False