"""
Главное приложение TUI с встроенной панелью логов
"""

import sys
import time
from pathlib import Path
from typing import Dict, Optional, List
from collections import deque
from datetime import datetime
import yaml
from rich.console import Console
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from loguru import logger

from tui.base_screen import BaseScreen
from tui.main_screen import MainScreen
from tui.emulators_screen import EmulatorsScreen
from tui.settings_screen import SettingsScreen
from tui.status_screen import StatusScreen
from orchestrator import get_orchestrator


class LogBuffer:
    """Буфер для хранения логов с поддержкой скроллинга"""

    def __init__(self, max_lines: int = 500):
        self.max_lines = max_lines
        self.logs = deque(maxlen=max_lines)
        self.scroll_offset = 0  # Смещение для скроллинга (0 = последние логи)

    def add(self, message: str, level: str = "INFO"):
        """Добавить лог в буфер"""
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Определяем цвет по уровню
        color_map = {
            "DEBUG": "dim",
            "INFO": "white",
            "SUCCESS": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold red"
        }
        color = color_map.get(level, "white")

        self.logs.append({
            'timestamp': timestamp,
            'level': level,
            'message': message,
            'color': color
        })

        # Если добавлен новый лог и мы в режиме автоскролла, сбрасываем offset
        if self.scroll_offset == 0:
            pass  # Остаемся внизу

    def scroll_up(self, lines: int = 5):
        """Прокрутка вверх"""
        max_offset = max(0, len(self.logs) - 10)
        self.scroll_offset = min(self.scroll_offset + lines, max_offset)

    def scroll_down(self, lines: int = 5):
        """Прокрутка вниз"""
        self.scroll_offset = max(0, self.scroll_offset - lines)

    def scroll_to_top(self):
        """Прокрутка в начало"""
        self.scroll_offset = max(0, len(self.logs) - 10)

    def scroll_to_bottom(self):
        """Прокрутка в конец (автоскролл)"""
        self.scroll_offset = 0

    def get_logs_panel(self, height: int = 20) -> Panel:
        """Получить панель с логами для отображения

        Args:
            height: Высота панели для расчета количества видимых строк
        """
        if not self.logs:
            content = Text("Логи появятся здесь...", style="dim")
            subtitle = ""
        else:
            content = Text()

            # Вычисляем диапазон видимых логов
            total_logs = len(self.logs)
            visible_lines = max(1, height - 3)  # Минус рамка и заголовок

            # Определяем какие логи показывать
            if self.scroll_offset == 0:
                # Автоскролл - показываем последние
                start_idx = max(0, total_logs - visible_lines)
                end_idx = total_logs
            else:
                # Ручной скролл - показываем с учетом offset
                end_idx = total_logs - self.scroll_offset
                start_idx = max(0, end_idx - visible_lines)

            # Формируем видимые логи
            visible_logs = list(self.logs)[start_idx:end_idx]
            for log in visible_logs:
                content.append(f"[{log['timestamp']}] ", style="cyan")
                content.append(f"{log['level']:<8} ", style=log['color'])
                content.append(f"| {log['message']}\n", style=log['color'])

            # Формируем информацию о скроллинге
            if self.scroll_offset > 0:
                subtitle = f"↑ Прокручено вверх | PgDn/End - вниз | Показано {start_idx+1}-{end_idx} из {total_logs}"
            else:
                subtitle = f"Автоскролл ✓ | PgUp/Home - прокрутить вверх | Всего логов: {total_logs}"

        return Panel(
            content,
            title="[cyan]📋 Логи[/cyan]",
            subtitle=subtitle,
            border_style="cyan"
        )


class BotTUIApp:
    """Главное приложение TUI с панелью логов"""

    def __init__(self):
        """Инициализация приложения"""
        self.console = Console()
        self.orchestrator = get_orchestrator()

        # Буфер логов (храним до 500 последних логов)
        self.log_buffer = LogBuffer(max_lines=500)

        # Загрузка конфигурации
        self.config_path = Path("configs/tui_config.yaml")
        self.config = self._load_config()

        # Инициализация экранов
        self.screens: Dict[str, BaseScreen] = {
            'main': MainScreen(self),
            'emulators': EmulatorsScreen(self),
            'settings': SettingsScreen(self),
            'status': StatusScreen(self),
        }

        self.current_screen_name = 'main'
        self.running = False

    def _load_config(self) -> Dict:
        """Загрузка конфигурации TUI"""
        default_config = {
            'max_concurrent_emulators': 5,
            'theme': 'default',
            'log_level': 'INFO',
            'auto_refresh_interval': 5
        }

        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    return {**default_config, **config.get('tui', {})}
            except Exception as e:
                logger.warning(f"Ошибка загрузки конфигурации TUI: {e}")
                return default_config
        else:
            self._save_default_config()
            return default_config

    def _save_default_config(self):
        """Сохранение конфига по умолчанию"""
        default_config = {
            'tui': {
                'max_concurrent_emulators': 5,
                'theme': 'default',
                'log_level': 'INFO',
                'auto_refresh_interval': 5
            }
        }

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.dump(default_config, f, allow_unicode=True)

    def save_config(self):
        """Сохранение текущей конфигурации"""
        try:
            config_data = {
                'tui': self.config
            }
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config_data, f, allow_unicode=True)
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения конфигурации: {e}")
            return False

    def switch_screen(self, screen_name: str):
        """Переключение между экранами"""
        if screen_name in self.screens:
            # Деактивируем текущий экран
            self.screens[self.current_screen_name].deactivate()

            # Переключаемся
            self.current_screen_name = screen_name

            # Активируем новый экран
            self.screens[screen_name].activate()

            self.log_buffer.add(f"Переход на экран: {screen_name}", "DEBUG")

    def render_with_logs(self) -> Layout:
        """Рендер текущего экрана с панелью логов внизу"""
        main_layout = Layout()

        # Получаем рендер текущего экрана
        screen_layout = self.screens[self.current_screen_name].render()

        # Получаем высоту терминала для расчета высоты панели логов
        terminal_height = self.console.height
        # Фиксированная высота для интерфейса (примерно 25-30 строк)
        interface_height = min(30, terminal_height - 15)
        # Логи занимают все оставшееся пространство
        logs_height = max(10, terminal_height - interface_height - 2)

        # Создаем панель логов с динамической высотой
        logs_panel = self.log_buffer.get_logs_panel(height=logs_height)

        # Компонуем: экран сверху (фиксированная высота), логи снизу (растягиваются)
        main_layout.split_column(
            Layout(screen_layout, size=interface_height),
            Layout(logs_panel)  # Без size - занимает все оставшееся место
        )

        return main_layout

    def _get_key(self) -> Optional[str]:
        """Получение нажатой клавиши (неблокирующее чтение)"""
        import select

        if sys.platform == 'win32':
            import msvcrt
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b'\x00', b'\xe0'):
                    ch2 = msvcrt.getch()
                    arrow_map = {
                        b'H': 'up',
                        b'P': 'down',
                        b'K': 'left',
                        b'M': 'right',
                        b'I': 'page_up',    # PageUp
                        b'Q': 'page_down',   # PageDown
                        b'G': 'home',        # Home
                        b'O': 'end'          # End
                    }
                    return arrow_map.get(ch2, None)
                try:
                    key = ch.decode('utf-8')
                    if key == '\r':
                        return 'enter'
                    elif key == '\x1b':
                        return 'escape'
                    elif key == '\x08':
                        return 'backspace'
                    return key
                except:
                    return None
            return None
        else:
            import termios
            import tty

            if not select.select([sys.stdin], [], [], 0)[0]:
                return None

            try:
                old_settings = termios.tcgetattr(sys.stdin)
                try:
                    tty.setraw(sys.stdin.fileno())
                    ch = sys.stdin.read(1)

                    if ch == '\x1b':
                        ch2 = sys.stdin.read(1)
                        if ch2 == '[':
                            ch3 = sys.stdin.read(1)
                            # Обработка расширенных последовательностей
                            if ch3 in '0123456789':
                                ch4 = sys.stdin.read(1)
                                if ch4 == '~':
                                    # Специальные клавиши
                                    key_map = {
                                        '5': 'page_up',   # PageUp
                                        '6': 'page_down', # PageDown
                                        '1': 'home',      # Home (альтернатива)
                                        '4': 'end'        # End (альтернатива)
                                    }
                                    return key_map.get(ch3, None)
                            else:
                                # Стрелки и другие клавиши
                                key_map = {
                                    'A': 'up',
                                    'B': 'down',
                                    'C': 'right',
                                    'D': 'left',
                                    'H': 'home',  # Home
                                    'F': 'end'    # End
                                }
                                return key_map.get(ch3, 'escape')
                        return 'escape'
                    elif ch == '\r' or ch == '\n':
                        return 'enter'
                    elif ch == ' ':
                        return ' '
                    elif ch == '\x7f':
                        return 'backspace'
                    else:
                        return ch
                finally:
                    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
            except Exception as e:
                logger.debug(f"Ошибка получения клавиши: {e}")
                return None

        return None

    def _setup_logging(self):
        """Настройка системы логирования с перехватом для TUI"""
        # Удаляем все существующие обработчики
        logger.remove()

        # Добавляем запись в файл
        log_path = Path("data/logs/tui.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_path,
            rotation="1 day",
            retention="7 days",
            level=self.config.get('log_level', 'INFO'),
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}"
        )

        # Добавляем кастомный обработчик для TUI буфера
        def tui_sink(message):
            """Кастомный sink для перехвата логов в TUI буфер"""
            record = message.record
            level = record["level"].name
            msg = record["message"]
            self.log_buffer.add(msg, level)

        logger.add(
            tui_sink,
            level="INFO",
            format="{message}"
        )

        self.log_buffer.add("🚀 Система логирования TUI инициализирована", "SUCCESS")

    def run(self):
        """Запуск TUI приложения"""
        self.running = True

        # Настраиваем логирование
        self._setup_logging()

        logger.info("=" * 60)
        logger.info("Beast Lord Bot - TUI Interface v2.1")
        logger.info("=" * 60)

        try:
            with Live(
                self.render_with_logs(),
                console=self.console,
                refresh_per_second=4,
                screen=True
            ) as live:

                while self.running:
                    # Получаем клавишу
                    key = self._get_key()

                    if key:
                        # Обрабатываем глобальные клавиши скроллинга логов
                        if key == 'page_up':
                            self.log_buffer.scroll_up(5)
                            live.update(self.render_with_logs())
                            continue
                        elif key == 'page_down':
                            self.log_buffer.scroll_down(5)
                            live.update(self.render_with_logs())
                            continue
                        elif key == 'home':
                            self.log_buffer.scroll_to_top()
                            live.update(self.render_with_logs())
                            continue
                        elif key == 'end':
                            self.log_buffer.scroll_to_bottom()
                            live.update(self.render_with_logs())
                            continue

                        # Обрабатываем клавишу текущим экраном
                        current_screen = self.screens[self.current_screen_name]
                        result = current_screen.handle_key(key)

                        # Обновляем экран с логами
                        try:
                            live.update(self.render_with_logs())
                        except Exception as e:
                            logger.error(f"Ошибка отрисовки экрана: {e}")

                        # Проверяем выход из приложения
                        if result is False and key.lower() == 'q' and self.current_screen_name == 'main':
                            self.running = False
                            logger.info("Выход из приложения по запросу пользователя")
                            break

                    # Автообновление экрана каждые N секунд
                    # (для отображения новых логов даже без нажатия клавиш)
                    time.sleep(0.1)

        except KeyboardInterrupt:
            logger.info("Получен сигнал прерывания (Ctrl+C)")
        except Exception as e:
            logger.error(f"Критическая ошибка TUI: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            # Останавливаем обработку при выходе
            if self.orchestrator.get_processing_status().get('processor_running'):
                logger.info("Останавливаем обработку перед выходом...")
                self.orchestrator.stop_processing()

            self.running = False
            logger.info("TUI приложение завершено")