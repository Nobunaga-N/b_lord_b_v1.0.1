"""
Экран настроек
"""

from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from loguru import logger

from tui.base_screen import BaseScreen


class SettingsScreen(BaseScreen):
    """Экран настроек"""

    def __init__(self, app):
        super().__init__(app)
        self.editing = False
        self.input_value = ""

    def activate(self):
        """При активации сбрасываем режим редактирования"""
        self.editing = False
        self.input_value = ""

    def render(self) -> Layout:
        """Отрисовка экрана настроек"""
        layout = Layout()

        # Заголовок
        title_panel = Panel(
            Text("Настройки", justify="center", style="bold cyan"),
            style="cyan"
        )

        # Текущее значение
        current_value = self.app.config.get('max_concurrent_emulators', 5)

        # Форма настроек
        settings_text = Text()
        settings_text.append("Максимум одновременных эмуляторов:\n\n", style="white")

        if self.editing:
            # Режим редактирования
            settings_text.append(f"[{self.input_value}_]\n\n", style="yellow bold")
            settings_text.append("Введите число и нажмите [ENTER]\n", style="dim")
            settings_text.append("Или [ESC] для отмены", style="dim")
        else:
            # Режим просмотра
            settings_text.append(f"[{current_value}]\n\n", style="green bold")
            settings_text.append("Нажмите [E] для изменения", style="dim")

        settings_panel = Panel(
            settings_text,
            title="[cyan]Конфигурация[/cyan]",
            border_style="cyan"
        )

        # Панель помощи
        help_table = Table(show_header=False, box=None, padding=(0, 2))
        help_table.add_column("Key", style="cyan bold", width=10)
        help_table.add_column("Action", style="white")

        if not self.editing:
            help_table.add_row("[E]", "Редактировать")
            help_table.add_row("[ESC]", "Назад")
        else:
            help_table.add_row("[0-9]", "Ввод цифр")
            help_table.add_row("[ENTER]", "Сохранить")
            help_table.add_row("[ESC]", "Отмена")

        help_panel = Panel(
            help_table,
            title="[cyan]Управление[/cyan]",
            border_style="cyan"
        )

        # Информационная панель
        info_text = Text()
        info_text.append("ℹ️  Информация:\n\n", style="bold")
        info_text.append("Максимальное количество эмуляторов,\n")
        info_text.append("которые могут работать одновременно.\n\n")
        info_text.append("Рекомендуемое значение: 5-8\n", style="dim")
        info_text.append("Зависит от мощности вашего ПК", style="dim")

        info_panel = Panel(
            info_text,
            border_style="cyan"
        )

        # Компоновка
        layout.split_column(
            Layout(title_panel, size=3),
            Layout(settings_panel),
            Layout(info_panel),
            Layout(help_panel, size=7)
        )

        return layout

    def handle_key(self, key: str) -> bool:
        """Обработка нажатий клавиш"""
        if not self.editing:
            # Режим просмотра
            if key.lower() == 'e':
                self.editing = True
                self.input_value = str(self.app.config.get('max_concurrent_emulators', 5))
                return True
            elif key.lower() == 'escape':
                self.app.switch_screen('main')
                return True
        else:
            # Режим редактирования
            if key.lower() == 'escape':
                self.editing = False
                self.input_value = ""
                return True
            elif key == 'enter':
                # Сохранение значения
                try:
                    value = int(self.input_value)
                    if 1 <= value <= 20:
                        self.app.config['max_concurrent_emulators'] = value
                        self.app.save_config()
                        logger.success(f"Настройка сохранена: max_concurrent = {value}")
                        self.editing = False
                        self.input_value = ""
                        return True
                    else:
                        logger.error("Значение должно быть от 1 до 20")
                except ValueError:
                    logger.error("Введите корректное число")
                return False
            elif key.isdigit():
                # Ввод цифры
                if len(self.input_value) < 2:  # Максимум 2 цифры
                    self.input_value += key
                    return True
            elif key == 'backspace':
                # Удаление последней цифры
                if self.input_value:
                    self.input_value = self.input_value[:-1]
                    return True

        return False