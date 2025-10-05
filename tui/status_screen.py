"""
Экран статуса работы бота
"""

from datetime import datetime, timedelta
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from loguru import logger

from tui.base_screen import BaseScreen


class StatusScreen(BaseScreen):
    """Экран статуса работы"""

    def __init__(self, app):
        super().__init__(app)
        self.start_time = None

    def activate(self):
        """При активации сохраняем время запуска"""
        status = self.app.orchestrator.get_processing_status()
        if status.get('processor_running') and self.start_time is None:
            self.start_time = datetime.now()

    def render(self) -> Layout:
        """Отрисовка экрана статуса"""
        layout = Layout()

        # Заголовок
        title_panel = Panel(
            Text("Статус работы", justify="center", style="bold cyan"),
            style="cyan"
        )

        # Получаем статус
        status = self.app.orchestrator.get_processing_status()
        queue_status = self.app.orchestrator.get_queue_status()

        # Основной статус
        main_status_text = Text()

        if status.get('processor_running'):
            main_status_text.append("Статус бота: ", style="white")
            main_status_text.append("🟢 Работает\n\n", style="bold green")

            # Время работы
            if self.start_time:
                uptime = datetime.now() - self.start_time
                hours, remainder = divmod(int(uptime.total_seconds()), 3600)
                minutes, seconds = divmod(remainder, 60)
                main_status_text.append(f"Время работы: {hours:02d}:{minutes:02d}:{seconds:02d}\n", style="cyan")
        else:
            main_status_text.append("Статус бота: ", style="white")
            main_status_text.append("⚪ Остановлен\n\n", style="bold")
            self.start_time = None

        main_status_text.append(f"Обработано аккаунтов: {status.get('total_processed', 0)}\n", style="green")
        main_status_text.append(f"Ошибок: {status.get('total_errors', 0)}\n",
                                style="red" if status.get('total_errors', 0) > 0 else "white")
        main_status_text.append(
            f"Активных эмуляторов: {status.get('active_slots', 0)}/{status.get('max_concurrent', 0)}\n")

        main_status_panel = Panel(
            main_status_text,
            title="[cyan]Общая информация[/cyan]",
            border_style="cyan"
        )

        # Очередь и последние действия
        if status.get('processor_running'):
            # Таблица очереди
            queue_table = Table(show_header=True, box=None)
            queue_table.add_column("Эмулятор", style="cyan")
            queue_table.add_column("Приоритет", style="yellow")

            priorities = queue_status.get('priorities', [])
            if priorities:
                for priority in priorities[:5]:  # Топ-5
                    emu_index = priority.emulator_index if hasattr(priority, 'emulator_index') else 'N/A'
                    total_priority = priority.total_priority if hasattr(priority, 'total_priority') else 0
                    queue_table.add_row(
                        f"Эмулятор {emu_index}",
                        f"{total_priority:.2f}"
                    )
            else:
                queue_table.add_row("Очередь пуста", "-")

            queue_panel = Panel(
                queue_table,
                title="[cyan]Очередь обработки (топ-5)[/cyan]",
                border_style="cyan"
            )

            # Последние действия (placeholder - нужна интеграция с логами)
            actions_text = Text()
            actions_text.append("• Система работает в фоновом режиме\n", style="dim")
            actions_text.append("• Детальные логи выводятся ниже\n", style="dim")
            actions_text.append("• Проверьте консоль для подробностей\n", style="dim")

            actions_panel = Panel(
                actions_text,
                title="[cyan]Активность[/cyan]",
                border_style="cyan"
            )

            # Компоновка в две колонки
            details_layout = Layout()
            details_layout.split_row(
                Layout(queue_panel),
                Layout(actions_panel)
            )
        else:
            details_layout = Layout(
                Panel(
                    Text("Бот остановлен. Запустите обработку из главного меню.", style="dim"),
                    border_style="cyan"
                )
            )

        # Панель помощи
        help_table = Table(show_header=False, box=None, padding=(0, 2))
        help_table.add_column("Key", style="cyan bold", width=10)
        help_table.add_column("Action", style="white")

        help_table.add_row("[R]", "Обновить")
        help_table.add_row("[ESC]", "Назад")

        help_panel = Panel(
            help_table,
            title="[cyan]Управление[/cyan]",
            border_style="cyan"
        )

        # Компоновка
        layout.split_column(
            Layout(title_panel, size=3),
            Layout(main_status_panel),
            Layout(details_layout),
            Layout(help_panel, size=6)
        )

        return layout

    def handle_key(self, key: str) -> bool:
        """Обработка нажатий клавиш"""
        key = key.lower()

        if key == 'escape':
            self.app.switch_screen('main')
            return True
        elif key == 'r':
            # Обновление экрана
            return True

        return False