#!/usr/bin/env python3
"""
КАРДИНАЛЬНО ПЕРЕРАБОТАННЫЙ ORCHESTRATOR.PY - ПРОМПТ 19 + FORCE-PROCESS

КРИТИЧЕСКИ ИСПРАВЛЕН:
✅ CLI команды с правильной инициализацией orchestrator
✅ Исправлено ожидание готовности эмулятора
✅ Добавлена задержка перед проверкой статуса
✅ Улучшена логика запуска эмуляторов
✅ ДОБАВЛЕНА команда force-process для принудительного тестирования

Динамическая обработка эмуляторов по готовности.
Workflow: получить готовые → запустить если слоты свободны →
обработать ПАРАЛЛЕЛЬНО (здания + исследования) → остановить.
БЕЗ мониторинга системных ресурсов.
"""

import sys
import time
import click
import threading
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

# Добавляем путь к проекту
project_root = Path(__file__).parent
sys.path.append(str(project_root))

from loguru import logger
from utils.emulator_discovery import EmulatorDiscovery
from utils.smart_ldconsole import SmartLDConsole
from utils.prime_time_manager import PrimeTimeManager
from utils.database import database
from scheduler import get_scheduler


@dataclass
class EmulatorSlot:
    """Информация о слоте обработки эмулятора"""
    status: str  # 'starting_emulator', 'processing_game', 'stopping_emulator', 'completed', 'error'
    start_time: datetime
    priority: object
    future: Optional[object] = None
    executor: Optional[ThreadPoolExecutor] = None


class DynamicEmulatorProcessor:
    """
    🚀 ДИНАМИЧЕСКИЙ ПРОЦЕССОР ЭМУЛЯТОРОВ

    Обрабатывает эмуляторы по готовности (НЕ батчи):
    - Максимум N одновременно (настраивается)
    - Умная очередь с приоритетами
    - ПАРАЛЛЕЛЬНАЯ обработка зданий И исследований
    """

    def __init__(self, orchestrator, max_concurrent: int = 5):
        self.orchestrator = orchestrator
        self.max_concurrent = max_concurrent
        self.running = False
        self.active_slots: Dict[int, EmulatorSlot] = {}
        self.slot_lock = threading.Lock()
        self.processor_thread = None

        logger.info(f"Инициализирован DynamicEmulatorProcessor с {max_concurrent} слотами")

    def start_processing(self) -> bool:
        """Запуск динамической обработки эмуляторов"""
        if self.running:
            logger.warning("Обработка уже запущена")
            return False

        logger.info("=== НАЧАЛО ДИНАМИЧЕСКОЙ ОБРАБОТКИ ЭМУЛЯТОРОВ ===")

        # КРИТИЧНО: Синхронизируем эмуляторы перед запуском
        logger.info("🔄 Синхронизация эмуляторов с базой данных...")
        self._sync_emulators_to_database()

        self.running = True
        self.processor_thread = threading.Thread(
            target=self._processing_loop,
            name="EmulatorProcessor",
            daemon=True
        )
        self.processor_thread.start()

        logger.success(f"🚀 Запущена динамическая обработка эмуляторов (макс {self.max_concurrent})")
        return True

    def stop_processing(self) -> bool:
        """Остановка динамической обработки"""
        if not self.running:
            logger.warning("Обработка не была запущена")
            return False

        logger.info("Останавливаем динамическую обработку...")
        self.running = False

        # Ждем завершения активных задач
        with self.slot_lock:
            for emulator_id, slot in self.active_slots.items():
                if slot.future and not slot.future.done():
                    logger.info(f"Ждем завершения обработки эмулятора {emulator_id}")

        # Ждем завершения основного потока
        if self.processor_thread and self.processor_thread.is_alive():
            self.processor_thread.join(timeout=5.0)

        logger.success("✅ Динамическая обработка остановлена")
        return True

    def get_status(self) -> Dict[str, Any]:
        """Получение статуса процессора"""
        with self.slot_lock:
            active_emulators = list(self.active_slots.keys())
            active_count = len(active_emulators)

        return {
            'running': self.running,
            'max_concurrent': self.max_concurrent,
            'active_slots': active_count,
            'free_slots': self.max_concurrent - active_count,
            'active_emulators': active_emulators
        }

    def force_process_emulator(self, emulator_id: int, ignore_prime_time: bool = False) -> Dict[str, Any]:
        """
        🧪 ПРИНУДИТЕЛЬНАЯ обработка эмулятора для тестирования

        Обходит обычную логику планировщика и прайм-таймов.
        Выполняется синхронно для немедленного результата.

        Args:
            emulator_id: ID эмулятора для обработки
            ignore_prime_time: Игнорировать ожидание прайм-тайма

        Returns:
            Результат обработки
        """
        logger.info(f"🧪 ПРИНУДИТЕЛЬНАЯ обработка эмулятора {emulator_id}")

        # Проверяем что эмулятор не обрабатывается сейчас
        with self.slot_lock:
            if emulator_id in self.active_slots:
                return {
                    'status': 'error',
                    'error': f'Эмулятор {emulator_id} уже обрабатывается'
                }

        try:
            # Получаем приоритет эмулятора от планировщика
            logger.info(f"📊 Получение данных эмулятора {emulator_id} от планировщика...")
            priority = self.orchestrator.scheduler.get_emulator_priority(emulator_id)

            if not priority:
                return {
                    'status': 'error',
                    'error': f'Эмулятор {emulator_id} не найден в планировщике'
                }

            logger.info(f"✅ Приоритет эмулятора {emulator_id}: {priority.total_priority}")
            logger.info(f"🎯 Рекомендуемые действия: {', '.join(priority.recommended_actions)}")

            # Проверяем прайм-тайм если не игнорируем
            if not ignore_prime_time and priority.waiting_for_prime_time:
                logger.warning(
                    f"⏰ Эмулятор {emulator_id} ожидает прайм-тайм через {priority.prime_time_wait_hours:.1f}ч")
                logger.info("💡 Используйте --ignore-prime-time для принудительного запуска")
                return {
                    'status': 'waiting_prime_time',
                    'wait_hours': priority.prime_time_wait_hours,
                    'message': 'Эмулятор ожидает прайм-тайм. Используйте --ignore-prime-time'
                }

            if ignore_prime_time and priority.waiting_for_prime_time:
                logger.warning(f"⚠️ ИГНОРИРУЕМ ожидание прайм-тайма для эмулятора {emulator_id}")

            # Выполняем обработку синхронно (не в потоке)
            logger.info(f"🚀 Начинаем принудительную обработку эмулятора {emulator_id}...")
            result = self._process_single_emulator(priority)

            logger.success(f"✅ Принудительная обработка эмулятора {emulator_id} завершена")
            return result

        except Exception as e:
            logger.error(f"❌ Ошибка принудительной обработки эмулятора {emulator_id}: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }

    def _update_slot_status(self, emulator_id: int, status: str):
        """Обновление статуса слота"""
        with self.slot_lock:
            if emulator_id in self.active_slots:
                self.active_slots[emulator_id].status = status

    def _processing_loop(self):
        """Основной цикл динамической обработки"""
        logger.info("🎯 Начат цикл динамической обработки")

        while self.running:
            try:
                # 0. КРИТИЧНО: Синхронизируем эмуляторы между Discovery и Database
                self._sync_emulators_to_database()

                # 1. Удаляем завершенные слоты
                self._clean_completed_slots()

                # 2. Получаем готовых эмуляторов по приоритету
                free_slots = self.max_concurrent - len(self.active_slots)
                if free_slots <= 0:
                    time.sleep(5.0)
                    continue

                ready_emulators = self.orchestrator.scheduler.get_ready_emulators_by_priority(free_slots)

                if not ready_emulators:
                    time.sleep(5.0)
                    continue

                # 3. Запускаем обработку готовых эмуляторов
                self._start_ready_emulators(ready_emulators)

                # Пауза между циклами
                time.sleep(2.0)

            except Exception as e:
                logger.error(f"❌ Ошибка в цикле обработки: {e}")
                time.sleep(10.0)

        logger.info("🔚 Цикл динамической обработки завершен")

    def _clean_completed_slots(self):
        """Освобождение завершенных слотов"""
        with self.slot_lock:
            completed_slots = []

            for emulator_id, slot in self.active_slots.items():
                if slot.future and slot.future.done():
                    try:
                        result = slot.future.result()
                        logger.info(f"✅ Слот {emulator_id} завершен: {result.get('status', 'unknown')}")
                    except Exception as e:
                        logger.error(f"❌ Слот {emulator_id} завершен с ошибкой: {e}")

                    completed_slots.append(emulator_id)

                    # Закрываем executor
                    if slot.executor:
                        slot.executor.shutdown(wait=False)

            # Удаляем завершенные слоты
            for emulator_id in completed_slots:
                del self.active_slots[emulator_id]

            if completed_slots:
                logger.debug(f"🧹 Освобождено слотов: {len(completed_slots)}")

    def _start_ready_emulators(self, ready_emulators: List[Any]):
        """Запуск обработки готовых эмуляторов"""
        for priority in ready_emulators:
            emulator_id = priority.emulator_index

            # Проверяем что слот свободен
            with self.slot_lock:
                if emulator_id in self.active_slots:
                    continue

            logger.info(f"🔄 Начало обработки эмулятора {emulator_id}")
            self._start_emulator_processing(priority)

    def _start_emulator_processing(self, priority: Any):
        """Запуск обработки одного эмулятора в отдельном потоке"""
        emulator_id = priority.emulator_index

        with self.slot_lock:
            if emulator_id in self.active_slots:
                logger.warning(f"Эмулятор {emulator_id} уже обрабатывается")
                return

            # Резервируем слот
            self.active_slots[emulator_id] = EmulatorSlot(
                status='starting',
                start_time=datetime.now(),
                priority=priority
            )

        # Запускаем в ThreadPoolExecutor
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"Emu{emulator_id}")
        future = executor.submit(self._process_single_emulator, priority)

        # Сохраняем future для отслеживания
        with self.slot_lock:
            if emulator_id in self.active_slots:
                self.active_slots[emulator_id].future = future
                self.active_slots[emulator_id].executor = executor

        logger.info(f"🎯 Запущена обработка эмулятора {emulator_id} (приоритет {priority.total_priority})")

    def _process_single_emulator(self, priority: Any) -> Dict[str, Any]:
        """
        ИСПРАВЛЕННАЯ обработка одного эмулятора по workflow:
        готовый → запуск (с правильным ожиданием) → ПАРАЛЛЕЛЬНАЯ обработка → остановка
        """
        emulator_id = priority.emulator_index
        start_time = datetime.now()

        try:
            logger.info(f"🔄 Начало обработки эмулятора {emulator_id}")

            # ЭТАП 1: Запуск эмулятора (ИСПРАВЛЕНО)
            self._update_slot_status(emulator_id, 'starting_emulator')

            if not self.orchestrator.ldconsole.is_running(emulator_id):
                logger.info(f"Запуск эмулятора {emulator_id}...")
                if not self.orchestrator.ldconsole.start_emulator(emulator_id):
                    raise Exception("Не удалось запустить эмулятор")

                # ИСПРАВЛЕНИЕ: Ожидание готовности с увеличенным таймаутом
                logger.info(f"Ожидание готовности ADB для эмулятора {emulator_id}...")
                if not self._wait_emulator_ready_fixed(emulator_id, timeout=120):
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

    def _wait_emulator_ready_fixed(self, index: int, timeout: float = 120.0) -> bool:
        """
        ИСПРАВЛЕННОЕ ожидание готовности эмулятора

        Ключевые исправления:
        ✅ Начальная задержка 15 секунд перед проверкой
        ✅ Более мягкая логика проверки is_running()
        ✅ Фокус на ADB соединении, а не на статусе процесса
        """
        logger.info(f"Ожидаем готовности эмулятора {index} (таймаут: {timeout}с)")

        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Даем эмулятору время на запуск
        logger.info(f"Даем эмулятору {index} время на запуск (15с)...")
        time.sleep(15.0)

        start_time = time.time()

        while time.time() - start_time < timeout:
            elapsed = time.time() - start_time

            # Проверяем ADB соединение напрямую
            adb_port = self.orchestrator.ldconsole.get_adb_port(index)
            if self.orchestrator.ldconsole.test_adb_connection(adb_port):
                logger.success(f"✅ Эмулятор {index} готов к ADB соединению через {elapsed:.1f}с")
                return True

            # Логируем прогресс каждые 10 секунд
            if int(elapsed) % 10 == 0 and elapsed > 0:
                logger.info(f"⏳ Ожидаем готовности эмулятора {index}: {elapsed:.0f}с/{timeout:.0f}с")

            time.sleep(2.0)

        logger.error(f"❌ Эмулятор {index} не готов к работе через {timeout}с")
        return False

    def _sync_emulators_to_database(self):
        """
        КРИТИЧНО: Синхронизация эмуляторов между EmulatorDiscovery и Database
        Это важно для правильной работы планировщика
        """
        try:
            # Получаем все эмуляторы из EmulatorDiscovery
            discovery_emulators = self.orchestrator.discovery.get_emulators()

            if not discovery_emulators:
                logger.debug("Нет эмуляторов для синхронизации")
                return

            # Синхронизируем каждый эмулятор в БД
            for emu_index, emu_info in discovery_emulators.items():
                try:
                    from utils.database import database
                    database.sync_emulator(
                        emulator_index=emu_index,
                        emulator_name=emu_info.name,
                        enabled=emu_info.enabled,
                        notes=emu_info.notes
                    )
                except Exception as e:
                    logger.error(f"Ошибка синхронизации эмулятора {emu_index}: {e}")

            logger.debug(f"✅ Синхронизировано {len(discovery_emulators)} эмуляторов в БД")

        except Exception as e:
            logger.error(f"❌ Критическая ошибка синхронизации эмуляторов: {e}")

    def _process_game_actions(self, priority: Any) -> Dict[str, Any]:
        """
        ПАРАЛЛЕЛЬНАЯ обработка игровых действий.
        Здесь будет интеграция с bot_worker.py в следующих промптах.
        """
        emulator_id = priority.emulator_index

        # ЗАГЛУШКА для тестирования
        logger.info(f"[ЗАГЛУШКА] ПАРАЛЛЕЛЬНАЯ обработка игровых действий для эмулятора {emulator_id}")

        # Имитируем обработку
        time.sleep(5)

        # Имитируем результаты
        return {
            'actions_completed': 3,
            'buildings_started': 1,
            'research_started': 1,
            'status': 'completed'
        }

    def _should_stop_emulator(self, priority: Any, game_result: Dict[str, Any]) -> bool:
        """
        Определение нужно ли останавливать эмулятор после обработки

        Логика остановки:
        - Останавливаем если следующая обработка через > 4 часов
        - Оставляем запущенным если < 1 часа до следующей обработки
        """
        emulator_id = priority.emulator_index

        # Получаем время следующей обработки
        next_check_time = self.orchestrator.scheduler.calculate_next_check_time(emulator_id)

        if next_check_time:
            time_until_next = (next_check_time - datetime.now()).total_seconds() / 3600

            if time_until_next > 4.0:
                logger.info(f"Следующая обработка через {time_until_next:.1f}ч - останавливаем эмулятор {emulator_id}")
                return True
            elif time_until_next < 1.0:
                logger.info(
                    f"Следующая обработка через {time_until_next:.1f}ч - оставляем эмулятор {emulator_id} запущенным")
                return False
            else:
                logger.info(
                    f"Следующая обработка через {time_until_next:.1f}ч - оставляем эмулятор {emulator_id} запущенным")
                return False

        # По умолчанию останавливаем
        logger.info(f"Не удалось определить время следующей обработки - останавливаем эмулятор {emulator_id}")
        return True


class Orchestrator:
    """
    🚀 КАРДИНАЛЬНО ПЕРЕРАБОТАННЫЙ ORCHESTRATOR

    Центральная система управления с интеграцией:
    - SmartLDConsole: управление эмуляторами LDPlayer
    - SmartScheduler: умное планирование с приоритетами
    - DynamicEmulatorProcessor: динамическая обработка по готовности
    - ПАРАЛЛЕЛЬНАЯ обработка зданий И исследований
    """

    def __init__(self):
        """Инициализация всех компонентов системы"""
        logger.info("🚀 Инициализация кардинально переработанного Orchestrator")

        # 1. Инициализация EmulatorDiscovery
        self.discovery = EmulatorDiscovery()
        logger.info(f"Инициализирован EmulatorDiscovery, конфиг: {self.discovery.config_path}")

        # 2. Инициализация SmartLDConsole
        ldconsole_path = self.discovery.find_ldplayer_path()
        if not ldconsole_path:
            logger.error("ldconsole.exe не найден!")
            raise RuntimeError("LDPlayer не найден")

        self.ldconsole = SmartLDConsole(ldconsole_path)
        logger.info(f"Инициализирован SmartLDConsole с путем: {ldconsole_path}")

        # 3. Инициализация PrimeTimeManager
        self.prime_time_manager = PrimeTimeManager()

        # 4. Инициализация SmartScheduler
        self.scheduler = get_scheduler(database, self.prime_time_manager)

        # 5. Инициализация DynamicEmulatorProcessor
        self.processor = DynamicEmulatorProcessor(self, max_concurrent=5)

        logger.info("🚀 Инициализирован кардинально переработанный Orchestrator")
        logger.info("  ✅ SmartLDConsole интеграция")
        logger.info("  ✅ SmartScheduler интеграция")
        logger.info("  ✅ Динамическая обработка по готовности")
        logger.info("  ✅ ПАРАЛЛЕЛЬНЫЕ здания И исследования")


# ========== ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР ORCHESTRATOR ==========

_orchestrator_instance = None


def get_orchestrator() -> Orchestrator:
    """Получение глобального экземпляра Orchestrator (паттерн Singleton)"""
    global _orchestrator_instance

    if _orchestrator_instance is None:
        _orchestrator_instance = Orchestrator()

    return _orchestrator_instance


# ========== CLI КОМАНДЫ ==========

@click.group()
def cli():
    """Beast Lord Bot - Кардинально переработанный Orchestrator v2.0"""
    pass


@cli.command()
def scan():
    """Сканирование эмуляторов LDPlayer"""
    logger.info("=== СКАНИРОВАНИЕ ЭМУЛЯТОРОВ ===")
    orchestrator = get_orchestrator()

    if orchestrator.discovery.scan_emulators():
        if orchestrator.discovery.save_config():
            logger.success("✅ Сканирование завершено, конфигурация сохранена")
        else:
            logger.error("❌ Ошибка сохранения конфигурации")
    else:
        logger.error("❌ Ошибка сканирования эмуляторов")


@cli.command()
@click.option('--enabled-only', is_flag=True, help='Показать только включенные эмуляторы')
@click.option('--disabled-only', is_flag=True, help='Показать только выключенные эмуляторы')
@click.option('--detailed', is_flag=True, help='Подробная информация')
def list(enabled_only: bool, disabled_only: bool, detailed: bool):
    """Список эмуляторов"""
    logger.info("=== СПИСОК ЭМУЛЯТОРОВ ===")
    orchestrator = get_orchestrator()

    if not orchestrator.discovery.load_config():
        logger.error("Конфигурация не найдена. Выполните сначала 'scan'")
        sys.exit(1)

    _show_emulators_list(enabled_only, disabled_only, detailed)


@cli.command()
@click.option('--id', 'emulator_id', required=True, type=int, help='ID эмулятора')
def enable(emulator_id: int):
    """Включить эмулятор"""
    logger.info(f"=== ВКЛЮЧЕНИЕ ЭМУЛЯТОРА {emulator_id} ===")
    orchestrator = get_orchestrator()

    if not orchestrator.discovery.load_config():
        logger.error("Конфигурация не найдена. Выполните сначала 'scan'")
        sys.exit(1)

    if orchestrator.discovery.enable_emulator(emulator_id):
        orchestrator.discovery.save_config()
        logger.success(f"✅ Эмулятор {emulator_id} включен")
    else:
        logger.error(f"❌ Не удалось включить эмулятор {emulator_id}")
        sys.exit(1)


@cli.command()
@click.option('--id', 'emulator_id', required=True, type=int, help='ID эмулятора')
def disable(emulator_id: int):
    """Выключить эмулятор"""
    logger.info(f"=== ВЫКЛЮЧЕНИЕ ЭМУЛЯТОРА {emulator_id} ===")
    orchestrator = get_orchestrator()

    if not orchestrator.discovery.load_config():
        logger.error("Конфигурация не найдена. Выполните сначала 'scan'")
        sys.exit(1)

    if orchestrator.discovery.disable_emulator(emulator_id):
        orchestrator.discovery.save_config()
        logger.success(f"✅ Эмулятор {emulator_id} выключен")
    else:
        logger.error(f"❌ Не удалось выключить эмулятор {emulator_id}")
        sys.exit(1)


@cli.command()
@click.option('--id', 'emulator_id', required=True, type=int, help='ID эмулятора')
@click.option('--text', 'notes_text', required=True, help='Текст заметки')
def note(emulator_id: int, notes_text: str):
    """Обновить заметку для эмулятора"""
    logger.info(f"=== Обновление заметки для эмулятора {emulator_id} ===")
    orchestrator = get_orchestrator()

    if not orchestrator.discovery.load_config():
        logger.error("Конфигурация не найдена. Выполните сначала 'scan'")
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
        logger.info(f"   Факторы приоритета:")
        for factor, value in priority.priority_factors.items():
            if value > 0:
                logger.info(f"     - {factor}: +{value}")
        logger.info(f"   Рекомендуемые действия: {', '.join(priority.recommended_actions)}")
        if priority.waiting_for_prime_time:
            logger.info(f"   🕐 Ожидает прайм-тайм через {priority.prime_time_wait_hours:.1f}ч")


@cli.command('force-process')
@click.option('--id', 'emulator_id', required=True, type=int, help='ID эмулятора для принудительной обработки')
@click.option('--ignore-prime-time', is_flag=True, help='Игнорировать ожидание прайм-тайма')
def force_process(emulator_id: int, ignore_prime_time: bool):
    """🧪 ПРИНУДИТЕЛЬНАЯ обработка эмулятора для тестирования (игнорирует прайм-тайм)"""
    logger.info(f"=== 🧪 ПРИНУДИТЕЛЬНАЯ ОБРАБОТКА ЭМУЛЯТОРА {emulator_id} ===")
    orchestrator = get_orchestrator()

    # Проверяем конфигурацию
    if not orchestrator.discovery.load_config():
        logger.error("Не удалось загрузить конфигурацию. Выполните сначала 'scan'")
        sys.exit(1)

    # Проверяем что эмулятор существует и включен
    enabled = orchestrator.discovery.get_enabled_emulators()
    if emulator_id not in enabled:
        logger.error(f"Эмулятор {emulator_id} не найден или не включен")
        logger.info("Включенные эмуляторы:")
        for idx, emu in enabled.items():
            logger.info(f"  ✅ ID {idx}: {emu.name}")
        sys.exit(1)

    emulator_info = enabled[emulator_id]
    logger.info(f"🎯 Целевой эмулятор: {emulator_info.name} (порт {emulator_info.adb_port})")

    # Показываем что будем игнорировать
    if ignore_prime_time:
        logger.warning("⚠️ ИГНОРИРУЕМ ожидание прайм-тайма!")

    # Принудительная обработка через процессор
    try:
        result = orchestrator.processor.force_process_emulator(emulator_id, ignore_prime_time)

        if result['status'] == 'success':
            logger.success(f"✅ Принудительная обработка эмулятора {emulator_id} завершена успешно!")
            logger.info(f"📊 Время обработки: {result['processing_time']:.1f}с")
            logger.info(f"🏗️ Зданий начато: {result.get('buildings_started', 0)}")
            logger.info(f"🔬 Исследований начато: {result.get('research_started', 0)}")
            logger.info(f"🎯 Действий выполнено: {result.get('actions_completed', 0)}")
        else:
            logger.error(f"❌ Ошибка принудительной обработки: {result.get('error', 'Неизвестная ошибка')}")
            sys.exit(1)

    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        sys.exit(1)


@cli.command()
def debug():
    """Отладочная информация для диагностики проблем"""
    logger.info("=== ОТЛАДОЧНАЯ ИНФОРМАЦИЯ ===")
    orchestrator = get_orchestrator()

    # Проверяем EmulatorDiscovery
    if not orchestrator.discovery.load_config():
        logger.error("❌ Не удалось загрузить конфигурацию EmulatorDiscovery")
        return

    discovery_emulators = orchestrator.discovery.get_enabled_emulators()
    logger.info(f"📁 EmulatorDiscovery: {len(discovery_emulators)} включенных эмуляторов")
    for idx, emu in discovery_emulators.items():
        logger.info(f"   ID {idx}: {emu.name} (включен: {emu.enabled})")

    # Синхронизируем эмуляторы в БД
    logger.info("\n🔄 Синхронизация эмуляторов с базой данных...")
    try:
        for emu_index, emu_info in orchestrator.discovery.get_emulators().items():
            from utils.database import database
            database.sync_emulator(
                emulator_index=emu_index,
                emulator_name=emu_info.name,
                enabled=emu_info.enabled,
                notes=emu_info.notes
            )
        logger.success("✅ Синхронизация завершена")
    except Exception as e:
        logger.error(f"❌ Ошибка синхронизации: {e}")
        return

    # Проверяем Database
    try:
        from utils.database import database
        db_emulators = database.get_all_emulators(enabled_only=True)
        logger.info(f"\n💾 Database: {len(db_emulators)} включенных эмуляторов")
        for emu in db_emulators:
            logger.info(f"   ID {emu['emulator_index']}: {emu['emulator_name']} (включен: {emu['enabled']})")
    except Exception as e:
        logger.error(f"❌ Ошибка доступа к базе данных: {e}")
        return

    # Проверяем Scheduler
    try:
        ready_emulators = orchestrator.scheduler.get_ready_emulators_by_priority(5)
        logger.info(f"\n🎯 Scheduler: {len(ready_emulators)} готовых эмуляторов")
        for i, priority in enumerate(ready_emulators, 1):
            logger.info(f"   {i}. Эмулятор {priority.emulator_index}: приоритет {priority.total_priority}")
    except Exception as e:
        logger.error(f"❌ Ошибка планировщика: {e}")
        return

    logger.success("\n✅ Отладка завершена! Если готовых эмуляторов 0 - проверьте данные в БД")


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
            logger.info(
                f"  {status_icon} ID {idx:2d}: {emu.name:15s}{running_status} (порт {emu.adb_port}) - {emu.notes}")


if __name__ == '__main__':
    try:
        cli()
    except Exception as e:
        logger.error(f"Ошибка CLI: {e}")
        sys.exit(1)