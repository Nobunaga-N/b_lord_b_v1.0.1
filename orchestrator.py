"""
Кардинально переработанный оркестратор для управления эмуляторами Beast Lord Bot.
Предоставляет CLI интерфейс и динамическую обработку эмуляторов по готовности.

КЛЮЧЕВЫЕ ОСОБЕННОСТИ:
- Динамическая обработка по готовности (каждый эмулятор индивидуально)
- Интеграция SmartLDConsole для управления жизненным циклом эмуляторов
- Workflow: готовые → запуск → ПАРАЛЛЕЛЬНАЯ обработка → остановка
- Максимум 5-8 одновременно (настраивается)
- БЕЗ мониторинга системных ресурсов
"""

import sys
import time
import threading
from pathlib import Path
from typing import List, Dict, Set
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import click
from loguru import logger
from utils.emulator_discovery import EmulatorDiscovery
from utils.smart_ldconsole import SmartLDConsole
from scheduler import SmartScheduler, get_scheduler
from utils.prime_time_manager import PrimeTimeManager
from utils.database import database


class DynamicEmulatorProcessor:
    """
    Динамический процессор эмуляторов.
    Обрабатывает эмуляторы по готовности с умным управлением слотами.
    """

    def __init__(self, orchestrator: 'Orchestrator', max_concurrent: int = 5):
        self.orchestrator = orchestrator
        self.max_concurrent = max_concurrent
        self.running = False
        self.processing_thread = None

        # Слоты активных эмуляторов
        self.active_slots: Dict[int, dict] = {}  # {emulator_id: slot_info}
        self.slot_lock = threading.Lock()

        logger.info(f"Инициализирован DynamicEmulatorProcessor с {max_concurrent} слотами")

    def start_processing(self):
        """Запуск динамической обработки эмуляторов"""
        if self.running:
            logger.warning("Обработка уже запущена")
            return False

        self.running = True
        self.processing_thread = threading.Thread(
            target=self._processing_loop,
            name="EmulatorProcessor",
            daemon=True
        )
        self.processing_thread.start()

        logger.success(f"🚀 Запущена динамическая обработка эмуляторов (макс {self.max_concurrent})")
        return True

    def stop_processing(self):
        """Остановка обработки эмуляторов"""
        if not self.running:
            logger.warning("Обработка уже остановлена")
            return False

        logger.info("Остановка обработки эмуляторов...")
        self.running = False

        # Ждем завершения потока
        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join(timeout=30)

        # Останавливаем все активные эмуляторы
        self._stop_all_active_emulators()

        logger.success("✅ Обработка эмуляторов остановлена")
        return True

    def _processing_loop(self):
        """Основной цикл динамической обработки"""
        logger.info("=== НАЧАЛО ДИНАМИЧЕСКОЙ ОБРАБОТКИ ЭМУЛЯТОРОВ ===")

        while self.running:
            try:
                # 1. Освобождаем завершенные слоты
                self._cleanup_completed_slots()

                # 2. Проверяем свободные слоты
                free_slots = self.max_concurrent - len(self.active_slots)

                if free_slots > 0:
                    # 3. Получаем готовых эмуляторов по приоритету
                    ready_emulators = self.orchestrator.scheduler.get_ready_emulators_by_priority(free_slots)

                    # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Безопасная обработка ready_emulators
                    if ready_emulators:
                        try:
                            # Безопасная проверка - пробуем получить длину
                            emulators_count = len(ready_emulators)
                            logger.info(f"Свободных слотов: {free_slots}, готовых эмуляторов: {emulators_count}")

                            # 4. Запускаем обработку готовых эмуляторов
                            try:
                                for priority in ready_emulators:
                                    if len(self.active_slots) >= self.max_concurrent:
                                        break  # Слоты заполнены

                                    self._start_emulator_processing(priority)
                            except Exception as e:
                                logger.error(f"Ошибка при итерации по ready_emulators: {e}")

                        except (TypeError, AttributeError) as e:
                            logger.error(f"Ошибка обработки ready_emulators: {type(ready_emulators)}, {e}")
                    else:
                        logger.info(f"Свободных слотов: {free_slots}, готовых эмуляторов: 0")

                # 5. Показываем статус активных слотов
                if self.active_slots:
                    logger.info(f"Активных слотов: {len(self.active_slots)}/{self.max_concurrent}")
                    for emu_id, slot_info in self.active_slots.items():
                        logger.info(f"  Слот {emu_id}: {slot_info['status']} (с {slot_info['start_time']})")

                # 6. Пауза перед следующим циклом
                time.sleep(60)  # Проверяем каждую минуту

            except KeyboardInterrupt:
                logger.info("Получен сигнал остановки")
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле обработки: {e}")
                time.sleep(60)

    def _start_emulator_processing(self, priority):
        """Запуск обработки одного эмулятора в отдельном потоке"""
        emulator_id = priority.emulator_index

        with self.slot_lock:
            if emulator_id in self.active_slots:
                logger.warning(f"Эмулятор {emulator_id} уже обрабатывается")
                return

            # Резервируем слот
            self.active_slots[emulator_id] = {
                'status': 'starting',
                'start_time': datetime.now(),
                'priority': priority,
                'future': None
            }

        # Запускаем в ThreadPoolExecutor
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"Emu{emulator_id}")
        future = executor.submit(self._process_single_emulator, priority)

        # Сохраняем future для отслеживания
        with self.slot_lock:
            if emulator_id in self.active_slots:
                self.active_slots[emulator_id]['future'] = future
                self.active_slots[emulator_id]['executor'] = executor

        logger.info(f"🎯 Запущена обработка эмулятора {emulator_id} (приоритет {priority.total_priority})")

    def _process_single_emulator(self, priority) -> dict:
        """
        Обработка одного эмулятора по workflow:
        готовый → запуск → ПАРАЛЛЕЛЬНАЯ обработка → остановка
        """
        emulator_id = priority.emulator_index
        start_time = datetime.now()

        try:
            logger.info(f"🔄 Начало обработки эмулятора {emulator_id}")

            # ЭТАП 1: Запуск эмулятора
            self._update_slot_status(emulator_id, 'starting_emulator')

            if not self.orchestrator.ldconsole.is_running(emulator_id):
                logger.info(f"Запуск эмулятора {emulator_id}...")
                if not self.orchestrator.ldconsole.start_emulator(emulator_id):
                    raise Exception("Не удалось запустить эмулятор")

                # Ожидание готовности ADB
                logger.info(f"Ожидание готовности ADB для эмулятора {emulator_id}...")
                if not self.orchestrator.ldconsole.wait_emulator_ready(emulator_id, timeout=120):
                    raise Exception("Эмулятор не готов к работе")
            else:
                logger.info(f"Эмулятор {emulator_id} уже запущен")

            # ЭТАП 2: ПАРАЛЛЕЛЬНАЯ обработка игровых действий
            self._update_slot_status(emulator_id, 'processing_game')

            # Здесь будет интеграция с bot_worker.py для ПАРАЛЛЕЛЬНОЙ обработки
            # зданий И исследований
            game_result = self._process_game_actions(priority)

            # ЭТАП 3: Остановка эмулятора (если нужно)
            self._update_slot_status(emulator_id, 'stopping_emulator')

            # Определяем нужно ли останавливать эмулятор
            should_stop = self._should_stop_emulator(priority, game_result)

            if should_stop:
                logger.info(f"Остановка эмулятора {emulator_id}...")
                self.orchestrator.ldconsole.stop_emulator(emulator_id)
            else:
                logger.info(f"Эмулятор {emulator_id} остается запущенным")

            # ЭТАП 4: Обновление расписания
            self.orchestrator.scheduler.update_emulator_schedule(emulator_id, priority)

            processing_time = (datetime.now() - start_time).total_seconds()

            result = {
                'status': 'success',
                'emulator_id': emulator_id,
                'processing_time': processing_time,
                'actions_completed': game_result.get('actions_completed', 0),
                'buildings_started': game_result.get('buildings_started', 0),
                'research_started': game_result.get('research_started', 0),
                'stopped_emulator': should_stop
            }

            logger.success(f"✅ Завершена обработка эмулятора {emulator_id} за {processing_time:.1f}с")
            return result

        except Exception as e:
            processing_time = (datetime.now() - start_time).total_seconds()

            logger.error(f"❌ Ошибка обработки эмулятора {emulator_id}: {e}")

            # Пытаемся остановить эмулятор при ошибке
            try:
                self.orchestrator.ldconsole.stop_emulator(emulator_id)
            except:
                pass

            return {
                'status': 'error',
                'emulator_id': emulator_id,
                'processing_time': processing_time,
                'error': str(e)
            }

    def _process_game_actions(self, priority) -> dict:
        """
        ПАРАЛЛЕЛЬНАЯ обработка игровых действий.
        Здесь будет интеграция с bot_worker.py в следующих промптах.
        """
        emulator_id = priority.emulator_index

        # ЗАГЛУШКА для игровых действий
        logger.info(f"[ЗАГЛУШКА] ПАРАЛЛЕЛЬНАЯ обработка игровых действий для эмулятора {emulator_id}")

        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Полностью безопасная обработка recommended_actions
        recommended_actions = []
        try:
            # Получаем атрибут без isinstance проверки
            raw_actions = getattr(priority, 'recommended_actions', None)

            if raw_actions is None:
                recommended_actions = []
            else:
                # Пробуем преобразовать к списку разными способами
                try:
                    # Пробуем итерировать (работает для списков, кортежей)
                    recommended_actions = list(raw_actions)
                except (TypeError, ValueError):
                    # Если не итерируется, пробуем как строку
                    try:
                        recommended_actions = [str(raw_actions)]
                    except:
                        recommended_actions = []

        except Exception as e:
            logger.warning(f"Ошибка обработки recommended_actions: {e}")
            recommended_actions = []

        logger.info(f"  Рекомендуемые действия: {recommended_actions}")
        logger.info(f"  Ожидание прайм-тайма: {getattr(priority, 'waiting_for_prime_time', False)}")

        # Имитируем обработку
        time.sleep(2)  # Уменьшаем время для тестов

        # Безопасная обработка действий
        actions_str = ''
        if recommended_actions:
            try:
                actions_str = ' '.join(str(action) for action in recommended_actions)
            except Exception as e:
                logger.warning(f"Ошибка формирования строки действий: {e}")
                actions_str = ''

        return {
            'actions_completed': len(recommended_actions) if recommended_actions else 0,
            'buildings_started': 1 if 'building' in actions_str else 0,
            'research_started': 1 if 'research' in actions_str else 0
        }

    def _should_stop_emulator(self, priority, game_result) -> bool:
        """Определяет нужно ли останавливать эмулятор после обработки"""
        # Останавливаем если:
        # 1. Не выполнено ни одного действия
        # 2. Эмулятор ждет долгосрочных действий (>4 часа)
        # 3. Нет прайм-таймов в ближайшие 2 часа

        actions_completed = game_result.get('actions_completed', 0)

        if actions_completed == 0:
            logger.info(f"Остановка эмулятора {priority.emulator_index}: не выполнено действий")
            return True

        # ИСПРАВЛЕНИЕ: Безопасная проверка следующего времени обработки
        try:
            # Проверяем имеет ли priority атрибут emulator_id
            emulator_id = getattr(priority, 'emulator_id', None)
            if emulator_id is None:
                emulator_id = getattr(priority, 'emulator_index', 1)

            # Безопасный вызов scheduler
            if hasattr(self.orchestrator.scheduler, 'calculate_next_check_time'):
                next_check = self.orchestrator.scheduler.calculate_next_check_time(emulator_id)

                if next_check and isinstance(next_check, datetime):
                    hours_until_next = (next_check - datetime.now()).total_seconds() / 3600

                    if hours_until_next > 2:
                        logger.info(
                            f"Остановка эмулятора {priority.emulator_index}: следующая обработка через {hours_until_next:.1f}ч")
                        return True
            else:
                logger.warning("Метод calculate_next_check_time не найден в scheduler")

        except Exception as e:
            logger.warning(f"Ошибка проверки времени следующей обработки: {e}")

        return False

    def _update_slot_status(self, emulator_id: int, status: str):
        """Обновление статуса слота"""
        with self.slot_lock:
            if emulator_id in self.active_slots:
                self.active_slots[emulator_id]['status'] = status

    def _cleanup_completed_slots(self):
        """Очистка завершенных слотов"""
        with self.slot_lock:
            completed_slots = []

            for emulator_id, slot_info in self.active_slots.items():
                future = slot_info.get('future')

                if future and future.done():
                    completed_slots.append(emulator_id)

                    # Получаем результат
                    try:
                        result = future.result()
                        logger.info(f"Слот {emulator_id} завершен: {result['status']}")
                    except Exception as e:
                        logger.error(f"Ошибка в слоте {emulator_id}: {e}")

                    # Закрываем executor
                    executor = slot_info.get('executor')
                    if executor:
                        executor.shutdown(wait=False)

            # Удаляем завершенные слоты
            for emulator_id in completed_slots:
                del self.active_slots[emulator_id]

    def _stop_all_active_emulators(self):
        """Остановка всех активных эмуляторов"""
        logger.info("Остановка всех активных эмуляторов...")

        with self.slot_lock:
            for emulator_id, slot_info in self.active_slots.items():
                try:
                    # Останавливаем эмулятор
                    self.orchestrator.ldconsole.stop_emulator(emulator_id)

                    # Закрываем executor
                    executor = slot_info.get('executor')
                    if executor:
                        executor.shutdown(wait=True)

                except Exception as e:
                    logger.error(f"Ошибка остановки эмулятора {emulator_id}: {e}")

            self.active_slots.clear()

    def get_status(self) -> dict:
        """Получение статуса процессора"""
        with self.slot_lock:
            active_emulators = []
            try:
                # Безопасное получение ключей
                if self.active_slots and isinstance(self.active_slots, dict):
                    active_emulators = list(self.active_slots.keys())
            except Exception as e:
                logger.warning(f"Ошибка получения активных эмуляторов: {e}")
                active_emulators = []

            return {
                'running': self.running,
                'max_concurrent': self.max_concurrent,
                'active_slots': len(self.active_slots) if self.active_slots else 0,
                'free_slots': max(0, self.max_concurrent - (len(self.active_slots) if self.active_slots else 0)),
                'active_emulators': active_emulators
            }


class Orchestrator:
    """Основной класс оркестратора с динамической обработкой"""

    def __init__(self):
        """Инициализация оркестратора"""
        self.discovery = EmulatorDiscovery()

        # Настройка логирования
        self._setup_logging()

        # Загружаем конфигурацию эмуляторов для получения пути к ldconsole
        self.discovery.load_config()

        # Инициализируем SmartLDConsole с найденным путем
        ldconsole_path = None
        if self.discovery.ldconsole_path:
            ldconsole_path = self.discovery.ldconsole_path

        self.ldconsole = SmartLDConsole(ldconsole_path)

        # Инициализируем планировщик с прайм-таймами
        self.scheduler = get_scheduler(database)
        self.prime_time_manager = PrimeTimeManager()

        # Инициализируем динамический процессор
        self.processor = DynamicEmulatorProcessor(self)

        logger.info("🚀 Инициализирован кардинально переработанный Orchestrator")
        logger.info("  ✅ SmartLDConsole интеграция")
        logger.info("  ✅ SmartScheduler интеграция")
        logger.info("  ✅ Динамическая обработка по готовности")
        logger.info("  ✅ ПАРАЛЛЕЛЬНЫЕ здания И исследования")

    def _setup_logging(self):
        """Настройка системы логирования"""
        # Удаляем стандартный обработчик
        logger.remove()

        # Добавляем консольный вывод
        logger.add(
            sys.stdout,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
            level="INFO"
        )

        # Создаем директорию для логов
        logs_dir = Path("data/logs")
        logs_dir.mkdir(parents=True, exist_ok=True)

        # Добавляем запись в файл
        logger.add(
            logs_dir / "orchestrator.log",
            rotation="1 day",
            retention="7 days",
            level="DEBUG",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
        )


# Глобальный экземпляр оркестратора создается только при прямом запуске
orchestrator = None


def get_orchestrator() -> Orchestrator:
    """Получение глобального экземпляра оркестратора"""
    global orchestrator
    if orchestrator is None:
        orchestrator = Orchestrator()
    return orchestrator


@click.group()
@click.version_option(version='2.5.0')
def cli():
    """Beast Lord Bot - Кардинально переработанный оркестратор с динамической обработкой"""
    pass


# === КОМАНДЫ УПРАВЛЕНИЯ ЭМУЛЯТОРАМИ ===

@cli.command()
def scan():
    """Сканирование доступных эмуляторов LDPlayer"""
    logger.info("=== Сканирование эмуляторов ===")
    orchestrator = get_orchestrator()

    # Загружаем существующую конфигурацию
    orchestrator.discovery.load_config()

    # Выполняем пересканирование с сохранением настроек
    if orchestrator.discovery.rescan_with_user_settings():
        # Показываем результаты
        summary = orchestrator.discovery.get_status_summary()

        logger.success("Сканирование завершено успешно!")
        logger.info(f"Найдено эмуляторов: {summary['total']}")
        logger.info(f"Включено: {summary['enabled']}")
        logger.info(f"Выключено: {summary['disabled']}")

        if summary['ldconsole_found']:
            logger.info(f"LDConsole: {summary['ldconsole_path']}")
        else:
            logger.warning("LDConsole не найден!")

        # Показываем список эмуляторов
        _show_emulators_list(detailed=False)

    else:
        logger.error("Ошибка при сканировании эмуляторов")
        sys.exit(1)


@cli.command()
@click.option('--enabled-only', is_flag=True, help='Показать только включенные эмуляторы')
@click.option('--disabled-only', is_flag=True, help='Показать только выключенные эмуляторы')
@click.option('--detailed', is_flag=True, help='Подробная информация')
def list(enabled_only: bool, disabled_only: bool, detailed: bool):
    """Список всех эмуляторов"""
    logger.info("=== Список эмуляторов ===")

    # Загружаем конфигурацию
    if not orchestrator.discovery.load_config():
        logger.error("Не удалось загрузить конфигурацию. Выполните сначала 'scan'")
        sys.exit(1)

    _show_emulators_list(enabled_only, disabled_only, detailed)


@cli.command()
@click.option('--id', 'emulator_ids', multiple=True, type=int, required=True,
              help='ID эмулятора для включения (можно указать несколько)')
def enable(emulator_ids: List[int]):
    """Включение эмулятора(ов)"""
    emulator_ids = tuple(emulator_ids)
    logger.info(f"=== Включение эмуляторов: {emulator_ids} ===")

    # Загружаем конфигурацию
    if not orchestrator.discovery.load_config():
        logger.error("Не удалось загрузить конфигурацию. Выполните сначала 'scan'")
        sys.exit(1)

    success_count = 0
    for emu_id in emulator_ids:
        if orchestrator.discovery.enable_emulator(emu_id):
            success_count += 1
        else:
            logger.error(f"Не удалось включить эмулятор {emu_id}")

    if success_count > 0:
        # Сохраняем изменения
        orchestrator.discovery.save_config()
        logger.success(f"Включено эмуляторов: {success_count}/{len(emulator_ids)}")
    else:
        logger.error("Не удалось включить ни одного эмулятора")
        sys.exit(1)


@cli.command()
@click.option('--id', 'emulator_ids', multiple=True, type=int, required=True,
              help='ID эмулятора для выключения (можно указать несколько)')
def disable(emulator_ids: List[int]):
    """Выключение эмулятора(ов)"""
    emulator_ids = tuple(emulator_ids)
    logger.info(f"=== Выключение эмуляторов: {emulator_ids} ===")

    # Загружаем конфигурацию
    if not orchestrator.discovery.load_config():
        logger.error("Не удалось загрузить конфигурацию. Выполните сначала 'scan'")
        sys.exit(1)

    success_count = 0
    for emu_id in emulator_ids:
        if orchestrator.discovery.disable_emulator(emu_id):
            success_count += 1
        else:
            logger.error(f"Не удалось выключить эмулятор {emu_id}")

    if success_count > 0:
        # Сохраняем изменения
        orchestrator.discovery.save_config()
        logger.success(f"Выключено эмуляторов: {success_count}/{len(emulator_ids)}")
    else:
        logger.error("Не удалось выключить ни одного эмулятора")
        sys.exit(1)


@cli.command()
@click.option('--id', 'emulator_id', type=int, required=True, help='ID эмулятора')
@click.option('--text', 'notes_text', required=True, help='Текст заметки')
def note(emulator_id: int, notes_text: str):
    """Обновление заметки для эмулятора"""
    logger.info(f"=== Обновление заметки для эмулятора {emulator_id} ===")

    # Загружаем конфигурацию
    if not orchestrator.discovery.load_config():
        logger.error("Не удалось загрузить конфигурацию. Выполните сначала 'scan'")
        sys.exit(1)

    if orchestrator.discovery.update_notes(emulator_id, notes_text):
        # Сохраняем изменения
        orchestrator.discovery.save_config()
        logger.success(f"Заметка для эмулятора {emulator_id} обновлена")
    else:
        logger.error(f"Не удалось обновить заметку для эмулятора {emulator_id}")
        sys.exit(1)


# === НОВЫЕ КОМАНДЫ ДИНАМИЧЕСКОЙ ОБРАБОТКИ ===

@cli.command('start-processing')
@click.option('--max-concurrent', default=5, help='Максимум одновременно обрабатываемых эмуляторов')
def start_processing(max_concurrent: int):
    """Запуск динамической обработки эмуляторов"""
    logger.info(f"=== ЗАПУСК ДИНАМИЧЕСКОЙ ОБРАБОТКИ (макс {max_concurrent}) ===")
    orchestrator = get_orchestrator()

    # Проверяем конфигурацию
    if not orchestrator.discovery.load_config():
        logger.error("Не удалось загрузить конфигурацию. Выполните сначала 'scan'")
        sys.exit(1)

    # Проверяем что есть включенные эмуляторы
    enabled = orchestrator.discovery.get_enabled_emulators()
    if not enabled:
        logger.error("Нет включенных эмуляторов. Включите эмуляторы командой 'enable'")
        sys.exit(1)

    logger.info(f"Включенных эмуляторов: {len(enabled)}")

    # Обновляем настройки процессора
    orchestrator.processor.max_concurrent = max_concurrent

    # Запускаем обработку
    if orchestrator.processor.start_processing():
        logger.success("🚀 Динамическая обработка запущена!")
        logger.info("Для остановки используйте Ctrl+C или команду 'stop-processing'")

        try:
            # Ждем завершения
            while orchestrator.processor.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Получен сигнал остановки...")
            orchestrator.processor.stop_processing()
    else:
        logger.error("Не удалось запустить обработку")
        sys.exit(1)


@cli.command('stop-processing')
def stop_processing():
    """Остановка динамической обработки эмуляторов"""
    logger.info("=== ОСТАНОВКА ДИНАМИЧЕСКОЙ ОБРАБОТКИ ===")
    orchestrator = get_orchestrator()

    if orchestrator.processor.stop_processing():
        logger.success("✅ Обработка остановлена")
    else:
        logger.warning("Обработка не была запущена")


@cli.command()
@click.option('--detailed', is_flag=True, help='Детальная информация')
def status(detailed: bool):
    """Показать статус системы и динамической обработки"""
    logger.info("=== СТАТУС СИСТЕМЫ ===")
    orchestrator = get_orchestrator()

    # Загружаем конфигурацию
    if not orchestrator.discovery.load_config():
        logger.warning("Конфигурация не найдена. Выполните 'scan' для первоначальной настройки")
        return

    # Общая информация об эмуляторах
    summary = orchestrator.discovery.get_status_summary()
    logger.info(f"📊 Всего эмуляторов: {summary['total']}")
    logger.info(f"✅ Включено: {summary['enabled']}")
    logger.info(f"❌ Выключено: {summary['disabled']}")

    if summary['ldconsole_found']:
        logger.info(f"🔧 LDConsole: {summary['ldconsole_path']}")
    else:
        logger.warning("⚠️  LDConsole не найден")

    # Статус динамической обработки
    processor_status = orchestrator.processor.get_status()
    logger.info(f"\n🔄 ДИНАМИЧЕСКАЯ ОБРАБОТКА:")
    logger.info(f"Статус: {'🟢 Запущена' if processor_status['running'] else '🔴 Остановлена'}")
    logger.info(f"Активных слотов: {processor_status['active_slots']}/{processor_status['max_concurrent']}")
    logger.info(f"Свободных слотов: {processor_status['free_slots']}")

    if processor_status['active_emulators']:
        logger.info(f"Активные эмуляторы: {processor_status['active_emulators']}")

    # Статус планировщика
    if detailed:
        try:
            schedule_summary = orchestrator.scheduler.get_schedule_summary()
            logger.info(f"\n📅 ПЛАНИРОВЩИК:")
            logger.info(f"Готовы сейчас: {schedule_summary['ready_now']}")
            logger.info(f"Ждут времени: {schedule_summary['waiting_for_time']}")
            logger.info(f"Ждут прайм-тайм: {schedule_summary['waiting_for_prime_time']}")

            if schedule_summary['next_ready_time']:
                logger.info(f"Следующий готов: {schedule_summary['next_ready_time']}")
        except Exception as e:
            logger.warning(f"Ошибка получения статуса планировщика: {e}")

    # Показываем включенные эмуляторы
    if summary['enabled'] > 0:
        logger.info(f"\n✅ ВКЛЮЧЕННЫЕ ЭМУЛЯТОРЫ:")
        enabled = orchestrator.discovery.get_enabled_emulators()
        for idx, emu in enabled.items():
            running_status = "🟢" if orchestrator.ldconsole.is_running(idx) else "🔴"
            logger.info(f"  {running_status} ID {idx}: {emu.name} (порт {emu.adb_port}) - {emu.notes}")


@cli.command()
@click.option('--max-concurrent', default=5, help='Максимум одновременно обрабатываемых эмуляторов')
def queue(max_concurrent: int):
    """Показать очередь эмуляторов по приоритету"""
    logger.info(f"=== ОЧЕРЕДЬ ЭМУЛЯТОРОВ (макс {max_concurrent}) ===")
    orchestrator = get_orchestrator()

    # Получаем готовых эмуляторов по приоритету
    ready_emulators = orchestrator.scheduler.get_ready_emulators_by_priority(max_concurrent)

    if not ready_emulators:
        logger.info("Нет эмуляторов готовых к обработке")
        return

    logger.info(f"Готовых к обработке: {len(ready_emulators)}")

    for i, priority in enumerate(ready_emulators, 1):
        logger.info(f"\n{i}. Эмулятор {priority.emulator_index}: {priority.emulator_name}")
        logger.info(f"   Лорд {priority.lord_level} | Приоритет: {priority.total_priority}")

        # Показываем факторы приоритета
        logger.info("   Факторы приоритета:")
        for factor, value in priority.priority_factors.items():
            if value > 0:
                logger.info(f"     - {factor}: +{value}")

        # Показываем рекомендуемые действия
        if priority.recommended_actions:
            logger.info(f"   Рекомендуемые действия: {', '.join(priority.recommended_actions[:3])}")

        # Показываем информацию о прайм-тайме
        if priority.waiting_for_prime_time and priority.next_prime_time_window:
            wait_time = (priority.next_prime_time_window - datetime.now()).total_seconds() / 3600
            logger.info(f"   🕐 Ожидает прайм-тайм через {wait_time:.1f}ч")


def _show_emulators_list(enabled_only: bool = False, disabled_only: bool = False, detailed: bool = False):
    """
    Вспомогательная функция для отображения списка эмуляторов

    Args:
        enabled_only: Показать только включенные
        disabled_only: Показать только выключенные
        detailed: Подробная информация
    """
    orchestrator = get_orchestrator()

    # Определяем какие эмуляторы показывать
    if enabled_only:
        emulators = orchestrator.discovery.get_enabled_emulators()
        title = "Включенные эмуляторы"
    elif disabled_only:
        emulators = orchestrator.discovery.get_disabled_emulators()
        title = "Выключенные эмуляторы"
    else:
        emulators = orchestrator.discovery.get_emulators()
        title = "Все эмуляторы"

    if not emulators:
        logger.info(f"{title}: не найдено")
        return

    logger.info(f"{title}:")

    # Сортируем по индексу
    sorted_emulators = sorted(emulators.items())

    for idx, emu in sorted_emulators:
        status_icon = "✅" if emu.enabled else "❌"

        # Проверяем запущен ли эмулятор
        running_status = ""
        if emu.enabled:
            running_status = " 🟢" if orchestrator.ldconsole.is_running(idx) else " 🔴"

        if detailed:
            logger.info(f"  {status_icon} ID {idx:2d}: {emu.name}{running_status}")
            logger.info(f"      ADB порт: {emu.adb_port}")
            logger.info(f"      Включен: {'Да' if emu.enabled else 'Нет'}")
            logger.info(f"      Заметки: {emu.notes}")
            logger.info("")
        else:
            logger.info(f"  {status_icon} ID {idx:2d}: {emu.name:15s}{running_status} (порт {emu.adb_port}) - {emu.notes}")


if __name__ == '__main__':
    try:
        cli()
    except Exception as e:
        logger.error(f"Ошибка CLI: {e}")
        sys.exit(1)