"""
Главный экран TUI интерфейса
"""

from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from loguru import logger

from tui.base_screen import BaseScreen


class MainScreen(BaseScreen):
    """Главный экран с меню навигации"""

    def render(self) -> Layout:
        """Отрисовка главного экрана"""
        layout = Layout()

        # Получаем статус системы
        status = self.app.orchestrator.get_processing_status()

        # Формируем таблицу меню
        menu_table = Table(show_header=False, box=None, padding=(0, 2))
        menu_table.add_column("Key", style="cyan bold", width=5)
        menu_table.add_column("Action", style="white")

        menu_table.add_row("[1]", "Эмуляторы")
        menu_table.add_row("[2]", "Настройки")
        menu_table.add_row("[3]", "Запустить бота" if not status.get('processor_running') else "Остановить бота")
        menu_table.add_row("[4]", "Статус работы")
        menu_table.add_row("", "")
        menu_table.add_row("[Q]", "Выход")

        # Формируем статус
        if status.get('configured'):
            status_icon = "🟢" if status.get('processor_running') else "⚪"
            status_text = "Работает" if status.get('processor_running') else "Остановлен"

            status_info = Text()
            status_info.append(f"Статус: {status_icon} {status_text}\n\n", style="bold")
            status_info.append(f"Всего эмуляторов: {status['total_emulators']}\n")
            status_info.append(f"Активных эмуляторов: {status['enabled_emulators']}\n")
            status_info.append(f"Макс одновременных: {status['max_concurrent']}\n")

            if status.get('processor_running'):
                status_info.append(f"\nОбработано: {status['total_processed']}\n", style="green")
                status_info.append(f"Ошибок: {status['total_errors']}\n",
                                   style="red" if status['total_errors'] > 0 else "white")
        else:
            status_info = Text()
            status_info.append("⚠️  Система не настроена\n\n", style="bold yellow")
            status_info.append("Выполните сканирование эмуляторов\n")
            status_info.append("в разделе 'Эмуляторы'")

        # Создаем панели
        title_panel = Panel(
            Text("Beast Lord Bot Controller v2.1", justify="center", style="bold cyan"),
            style="cyan"
        )

        status_panel = Panel(
            status_info,
            title="[cyan]Информация[/cyan]",
            border_style="cyan"
        )

        menu_panel = Panel(
            menu_table,
            title="[cyan]Меню[/cyan]",
            border_style="cyan"
        )

        # Компоновка
        layout.split_column(
            Layout(title_panel, size=3),
            Layout(status_panel),
            Layout(menu_panel)
        )

        return layout

    def handle_key(self, key: str) -> bool:
        """Обработка нажатий клавиш на главном экране"""
        key = key.lower()

        if key == '1':
            self.app.switch_screen('emulators')
            return True
        elif key == '2':
            self.app.switch_screen('settings')
            return True
        elif key == '3':
            # Запуск/остановка бота
            status = self.app.orchestrator.get_processing_status()
            if status.get('processor_running'):
                self.app.orchestrator.stop_processing()
            else:
                # Получаем max_concurrent из настроек
                max_concurrent = self.app.config.get('max_concurrent_emulators', 5)
                self.app.orchestrator.start_processing(max_concurrent)
            return True
        elif key == '4':
            self.app.switch_screen('status')
            return True
        elif key == 'q':
            return False  # Выход из приложения

        return False