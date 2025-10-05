"""
Кардинально переработанный Orchestrator v2.1
РЕФАКТОРИНГ: БЕЗ CLI - только бизнес-логика для TUI
ПРОМПТ 19 + ПРОМПТ 20: Динамическая обработка + мониторинг

КРИТИЧНО: Динамическая обработка эмуляторов по готовности
БЕЗ мониторинга системных ресурсов
"""

import sys
import time
import threading
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

from loguru import logger
from utils.database import Database
from utils.emulator_discovery import EmulatorDiscovery
from utils.smart_ldconsole import SmartLDConsole
from utils.prime_time_manager import PrimeTimeManager
from scheduler import get_scheduler


# ========== DATACLASSES ==========

@dataclass
class EmulatorSlot:
    """Информация о слоте обработки эмулятора"""
    status: str  # 'starting_emulator', 'processing_game', 'stopping_emulator', 'completed', 'error'
    start_time: datetime
    priority: object
    future: Optional[object] = None
    executor: Optional[ThreadPoolExecutor] = None
    # Детальная информация о прогрессе
    buildings_started: int = 0
    research_started: int = 0
    actions_completed: int = 0
    last_activity: Optional[datetime] = None
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.last_activity is None:
            self.last_activity = datetime.now()


@dataclass
class ProcessingStats:
    """Статистика обработки для мониторинга"""
    total_processed: int = 0
    successful_sessions: int = 0
    failed_sessions: int = 0
    total_buildings_started: int = 0
    total_research_started: int = 0
    total_actions_completed: int = 0
    average_processing_time: float = 0.0
    last_reset: datetime = None

    def __post_init__(self):
        if self.last_reset is None:
            self.last_reset = datetime.now()


# ========== DYNAMIC PROCESSOR ==========

class DynamicEmulatorProcessor:
    """
    Динамический процессор эмуляторов - ПРОМПТ 20

    Функции:
    - Детальный мониторинг активных эмуляторов
    - Статистика ПАРАЛЛЕЛЬНОГО прогресса зданий И исследований
    - Улучшенное освобождение слотов
    - Мониторинг производительности
    """

    def __init__(self, orchestrator, max_concurrent: int = 5):
        self.orchestrator = orchestrator
        self.max_concurrent = max_concurrent
        self.running = False
        self.active_slots: Dict[int, EmulatorSlot] = {}
        self.slot_lock = threading.Lock()
        self.processor_thread = None

        # Статистика для мониторинга
        self.stats = ProcessingStats()
        self.stats_lock = threading.Lock()

        logger.info(f"Инициализирован DynamicEmulatorProcessor с {max_concurrent} слотами + мониторинг")

    def start_processing(self) -> bool:
        """Запуск динамической обработки эмуляторов"""
        if self.running:
            logger.warning("Обработка уже запущена")
            return False

        logger.info("=== НАЧАЛО ДИНАМИЧЕСКОЙ ОБРАБОТКИ ЭМУЛЯТОРОВ ===")

        # Синхронизируем эмуляторы перед запуском
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

        # Ждем завершения активных задач с таймаутом
        with self.slot_lock:
            active_futures = []
            for emulator_id, slot in self.active_slots.items():
                if slot.future and not slot.future.done():
                    logger.info(f"Ждем завершения обработки эмулятора {emulator_id}")
                    active_futures.append((emulator_id, slot.future))

        # Ждем завершения с таймаутом
        for emulator_id, future in active_futures:
            try:
                future.result(timeout=30.0)
            except Exception as e:
                logger.warning(f"Эмулятор {emulator_id} завершился с ошибкой: {e}")

        # Ждем завершения основного потока
        if self.processor_thread and self.processor_thread.is_alive():
            self.processor_thread.join(timeout=5.0)

        # Очищаем все слоты
        with self.slot_lock:
            self.active_slots.clear()

        logger.success("✅ Динамическая обработка остановлена")
        return True

    def get_status(self) -> Dict[str, Any]:
        """Получение статуса процессора"""
        with self.slot_lock:
            active_count = len(self.active_slots)
            active_emulators = list(self.active_slots.keys())

        with self.stats_lock:
            stats_dict = {
                'total_processed': self.stats.total_processed,
                'successful_sessions': self.stats.successful_sessions,
                'failed_sessions': self.stats.failed_sessions,
                'total_buildings_started': self.stats.total_buildings_started,
                'total_research_started': self.stats.total_research_started,
                'total_actions_completed': self.stats.total_actions_completed,
                'average_processing_time': self.stats.average_processing_time
            }

        return {
            'running': self.running,
            'active_slots': active_count,
            'max_concurrent': self.max_concurrent,
            'active_emulators': active_emulators,
            'total_stats': stats_dict
        }

    def get_detailed_active_emulators(self) -> List[Dict[str, Any]]:
        """Получение детальной информации об активных эмуляторах"""
        detailed_info = []

        with self.slot_lock:
            for emulator_id, slot in self.active_slots.items():
                elapsed = (datetime.now() - slot.start_time).total_seconds()

                info = {
                    'emulator_id': emulator_id,
                    'status': slot.status,
                    'elapsed_time': elapsed,
                    'buildings_started': slot.buildings_started,
                    'research_started': slot.research_started,
                    'actions_completed': slot.actions_completed,
                    'last_activity': slot.last_activity.isoformat() if slot.last_activity else None,
                    'errors': slot.errors
                }
                detailed_info.append(info)

        return detailed_info

    def reset_stats(self):
        """Сброс статистики"""
        with self.stats_lock:
            self.stats = ProcessingStats()
        logger.info("📊 Статистика обработки сброшена")

    def _processing_loop(self):
        """Основной цикл обработки"""
        logger.info("🔄 Запущен основной цикл динамической обработки")

        while self.running:
            try:
                # Проверяем свободные слоты
                with self.slot_lock:
                    free_slots = self.max_concurrent - len(self.active_slots)

                if free_slots > 0:
                    # Получаем готовые эмуляторы по приоритету
                    ready_emulators = self.orchestrator.scheduler.get_ready_emulators_by_priority(
                        max_count=free_slots
                    )

                    for priority in ready_emulators:
                        if not self.running:
                            break

                        # Проверяем что эмулятор еще не обрабатывается
                        with self.slot_lock:
                            if priority.emulator_index in self.active_slots:
                                continue

                        # Запускаем обработку эмулятора
                        self._start_emulator_processing(priority)

                # Проверяем завершенные слоты
                self._check_completed_slots()

                # Пауза перед следующей итерацией
                time.sleep(2.0)

            except Exception as e:
                logger.error(f"❌ Ошибка в цикле обработки: {e}")
                time.sleep(5.0)

        logger.info("🛑 Основной цикл динамической обработки завершен")

    def _start_emulator_processing(self, priority):
        """Запуск обработки одного эмулятора"""
        emulator_id = priority.emulator_index

        logger.info(f"🚀 Запуск обработки эмулятора {emulator_id} (приоритет: {priority.total_priority})")

        # Создаем слот
        slot = EmulatorSlot(
            status='starting_emulator',
            start_time=datetime.now(),
            priority=priority
        )

        # Создаем executor для этого слота
        slot.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"Emu{emulator_id}")

        # Запускаем обработку в отдельном потоке
        slot.future = slot.executor.submit(self._process_single_emulator, emulator_id)

        # Сохраняем слот
        with self.slot_lock:
            self.active_slots[emulator_id] = slot

    def _check_completed_slots(self):
        """Проверка и освобождение завершенных слотов"""
        completed_slots = []

        with self.slot_lock:
            for emulator_id, slot in list(self.active_slots.items()):
                if slot.future and slot.future.done():
                    completed_slots.append(emulator_id)

        # Обрабатываем завершенные слоты
        for emulator_id in completed_slots:
            self._handle_completed_slot(emulator_id)

    def _handle_completed_slot(self, emulator_id: int):
        """Обработка завершенного слота"""
        with self.slot_lock:
            slot = self.active_slots.get(emulator_id)
            if not slot:
                return

            try:
                # Получаем результат
                result = slot.future.result(timeout=1.0)

                # Обновляем статистику
                self._update_stats_for_completed_slot(slot, result)

                # Закрываем executor
                if slot.executor:
                    slot.executor.shutdown(wait=False)

                logger.info(f"✅ Слот эмулятора {emulator_id} освобожден")

            except Exception as e:
                logger.error(f"❌ Ошибка при освобождении слота {emulator_id}: {e}")

            finally:
                # Удаляем слот
                self.active_slots.pop(emulator_id, None)

    def _update_stats_for_completed_slot(self, slot: EmulatorSlot, result: Dict):
        """Обновление статистики после завершения обработки"""
        with self.stats_lock:
            self.stats.total_processed += 1

            if result.get('status') == 'success':
                self.stats.successful_sessions += 1
                self.stats.total_buildings_started += result.get('buildings_started', 0)
                self.stats.total_research_started += result.get('research_started', 0)
                self.stats.total_actions_completed += result.get('actions_completed', 0)
            else:
                self.stats.failed_sessions += 1

            # Обновляем среднее время обработки
            processing_time = result.get('processing_time', 0)
            if self.stats.total_processed > 1:
                self.stats.average_processing_time = (
                    (self.stats.average_processing_time * (self.stats.total_processed - 1) + processing_time)
                    / self.stats.total_processed
                )
            else:
                self.stats.average_processing_time = processing_time

    def _process_single_emulator(self, emulator_id: int) -> Dict[str, Any]:
        """Обработка одного эмулятора"""
        start_time = datetime.now()

        try:
            # 1. Запуск эмулятора
            self._update_slot_status(emulator_id, 'starting_emulator')
            logger.info(f"🔧 Запуск эмулятора {emulator_id}")

            if not self.orchestrator.ldconsole.start_emulator(emulator_id, wait_ready=False):
                raise Exception(f"Не удалось запустить эмулятор {emulator_id}")

            # 2. Ожидание готовности ADB
            if not self._wait_for_adb_ready(emulator_id, max_wait=90):
                raise Exception(f"Таймаут ожидания ADB для эмулятора {emulator_id}")

            # 3. Обработка игры (временная симуляция)
            self._update_slot_status(emulator_id, 'processing_game')
            logger.info(f"🎮 Обработка игры для эмулятора {emulator_id}")

            processing_result = self._simulate_parallel_game_processing(emulator_id)

            # Обновляем прогресс в слоте
            with self.slot_lock:
                if emulator_id in self.active_slots:
                    slot = self.active_slots[emulator_id]
                    slot.buildings_started = processing_result.get('buildings_started', 0)
                    slot.research_started = processing_result.get('research_started', 0)
                    slot.actions_completed = processing_result.get('actions_completed', 0)
                    slot.last_activity = datetime.now()

            # 4. Остановка эмулятора
            self._update_slot_status(emulator_id, 'stopping_emulator')
            logger.info(f"⏹️  Остановка эмулятора {emulator_id}")

            if self.orchestrator.ldconsole.stop_emulator(emulator_id):
                logger.success(f"✅ Эмулятор {emulator_id} остановлен")
            else:
                logger.warning(f"⚠️ Не удалось остановить эмулятор {emulator_id}")

            # Финальный результат
            processing_time = (datetime.now() - start_time).total_seconds()
            result = {
                'status': 'success',
                'processing_time': processing_time,
                'buildings_started': processing_result.get('buildings_started', 0),
                'research_started': processing_result.get('research_started', 0),
                'actions_completed': processing_result.get('actions_completed', 0)
            }

            logger.success(f"✅ Обработка эмулятора {emulator_id} завершена за {processing_time:.1f}с")
            return result

        except Exception as e:
            error_msg = f"Ошибка обработки эмулятора {emulator_id}: {e}"
            logger.error(error_msg)
            self._update_slot_status(emulator_id, 'error', error=error_msg)

            # Пытаемся остановить эмулятор при ошибке
            try:
                self.orchestrator.ldconsole.stop_emulator(emulator_id)
            except:
                pass

            return {
                'status': 'error',
                'error': error_msg,
                'processing_time': (datetime.now() - start_time).total_seconds()
            }

    def _update_slot_status(self, emulator_id: int, status: str, error: str = None):
        """Обновление статуса слота"""
        with self.slot_lock:
            if emulator_id in self.active_slots:
                slot = self.active_slots[emulator_id]
                slot.status = status
                slot.last_activity = datetime.now()
                if error:
                    slot.errors.append(error)

    def _wait_for_adb_ready(self, emulator_id: int, max_wait: int = 90) -> bool:
        """Ожидание готовности ADB"""
        logger.info(f"⏳ Ожидание готовности ADB для эмулятора {emulator_id} (макс {max_wait}с)")

        start_time = datetime.now()
        last_status_log = start_time

        while (datetime.now() - start_time).total_seconds() < max_wait:
            if (datetime.now() - last_status_log).total_seconds() >= 10:
                elapsed = (datetime.now() - start_time).total_seconds()
                logger.info(f"🔍 Проверка ADB эмулятора {emulator_id} - прошло {elapsed:.0f}с")
                last_status_log = datetime.now()

            if self.orchestrator.ldconsole.is_adb_ready(emulator_id):
                total_time = (datetime.now() - start_time).total_seconds()
                logger.success(f"✅ ADB готов для эмулятора {emulator_id} за {total_time:.1f}с")
                return True

            time.sleep(5.0)

        total_time = (datetime.now() - start_time).total_seconds()
        logger.error(f"❌ Таймаут ожидания ADB для эмулятора {emulator_id} ({total_time:.1f}с)")
        return False

    def _simulate_parallel_game_processing(self, emulator_id: int) -> Dict[str, Any]:
        """ВРЕМЕННАЯ симуляция ПАРАЛЛЕЛЬНОЙ обработки игры (до промпта 21)"""
        logger.info(f"🎮 СИМУЛЯЦИЯ ПАРАЛЛЕЛЬНОЙ обработки игры для эмулятора {emulator_id}")

        time.sleep(5.0)

        import random
        return {
            'buildings_started': random.randint(1, 3),
            'research_started': random.randint(0, 1),
            'actions_completed': random.randint(3, 8)
        }

    def _sync_emulators_to_database(self):
        """Синхронизация эмуляторов между Discovery и Database"""
        try:
            emulators = self.orchestrator.discovery.get_emulators()
            for emu_index, emu_info in emulators.items():
                self.orchestrator.database.sync_emulator(
                    emulator_index=emu_index,
                    emulator_name=emu_info.name,
                    enabled=emu_info.enabled,
                    notes=emu_info.notes
                )
        except Exception as e:
            logger.warning(f"Ошибка синхронизации эмуляторов: {e}")


# ========== ORCHESTRATOR ==========

class Orchestrator:
    """
    Умное управление очередью эмуляторов с ПАРАЛЛЕЛЬНОЙ логикой
    Кардинально переработанная версия 2.1 (TUI)
    """

    def __init__(self):
        """Инициализация Orchestrator с компонентами системы"""
        logger.info("🚀 Инициализация Orchestrator v2.1 (TUI version)")

        # 0. Инициализация базы данных
        self.database = Database()

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
        self.scheduler = get_scheduler(self.database, self.prime_time_manager)

        # 5. Инициализация DynamicEmulatorProcessor
        self.processor = DynamicEmulatorProcessor(self, max_concurrent=5)

        logger.info("✅ Orchestrator инициализирован успешно")
        logger.info("  ✅ SmartLDConsole интеграция")
        logger.info("  ✅ SmartScheduler интеграция")
        logger.info("  ✅ Динамическая обработка по готовности")
        logger.info("  ✅ ПАРАЛЛЕЛЬНЫЕ здания И исследования")

    # ========== МЕТОДЫ УПРАВЛЕНИЯ ЭМУЛЯТОРАМИ ==========

    def scan_emulators(self) -> bool:
        """Сканирование эмуляторов LDPlayer"""
        logger.info("Сканирование эмуляторов")

        if self.discovery.scan_emulators():
            if self.discovery.save_config():
                logger.success("✅ Сканирование завершено, конфигурация сохранена")
                return True
            else:
                logger.error("❌ Ошибка сохранения конфигурации")
                return False
        else:
            logger.error("❌ Ошибка сканирования эмуляторов")
            return False

    def get_emulators_list(self, enabled_only: bool = False,
                          disabled_only: bool = False) -> Dict[int, any]:
        """
        Получить список эмуляторов

        Args:
            enabled_only: Только включенные
            disabled_only: Только выключенные

        Returns:
            Словарь эмуляторов
        """
        if enabled_only:
            return self.discovery.get_enabled_emulators()
        elif disabled_only:
            return self.discovery.get_disabled_emulators()
        else:
            return self.discovery.get_emulators()

    def enable_emulator(self, emulator_id: int) -> bool:
        """Включить эмулятор"""
        if not self.discovery.load_config():
            logger.error("Конфигурация не найдена. Выполните сначала scan")
            return False

        if self.discovery.enable_emulator(emulator_id):
            self.discovery.save_config()
            logger.success(f"✅ Эмулятор {emulator_id} включен")
            return True
        else:
            logger.error(f"❌ Не удалось включить эмулятор {emulator_id}")
            return False

    def disable_emulator(self, emulator_id: int) -> bool:
        """Выключить эмулятор"""
        if not self.discovery.load_config():
            logger.error("Конфигурация не найдена. Выполните сначала scan")
            return False

        if self.discovery.disable_emulator(emulator_id):
            self.discovery.save_config()
            logger.success(f"✅ Эмулятор {emulator_id} выключен")
            return True
        else:
            logger.error(f"❌ Не удалось выключить эмулятор {emulator_id}")
            return False

    def update_emulator_notes(self, emulator_id: int, notes: str) -> bool:
        """Обновить заметки для эмулятора"""
        if not self.discovery.load_config():
            logger.error("Конфигурация не найдена")
            return False

        if self.discovery.update_notes(emulator_id, notes):
            self.discovery.save_config()
            logger.success(f"Заметка для эмулятора {emulator_id} обновлена")
            return True
        else:
            logger.error(f"Не удалось обновить заметку для эмулятора {emulator_id}")
            return False

    # ========== МЕТОДЫ УПРАВЛЕНИЯ ОБРАБОТКОЙ ==========

    def start_processing(self, max_concurrent: int = 5) -> bool:
        """
        Запустить динамическую обработку эмуляторов

        Args:
            max_concurrent: Максимум одновременно обрабатываемых эмуляторов

        Returns:
            True если запуск успешен
        """
        logger.info(f"Запуск динамической обработки (макс {max_concurrent})")

        # Проверяем конфигурацию
        if not self.discovery.load_config():
            logger.error("Не удалось загрузить конфигурацию")
            return False

        # Проверяем что есть включенные эмуляторы
        enabled = self.discovery.get_enabled_emulators()
        if not enabled:
            logger.error("Нет включенных эмуляторов")
            return False

        logger.info(f"Включенных эмуляторов: {len(enabled)}")

        # Обновляем настройки процессора
        self.processor.max_concurrent = max_concurrent

        # Запускаем обработку
        if self.processor.start_processing():
            logger.success("🚀 Динамическая обработка запущена!")
            return True
        else:
            logger.error("Не удалось запустить обработку")
            return False

    def stop_processing(self) -> bool:
        """Остановить динамическую обработку"""
        logger.info("Остановка динамической обработки")

        if self.processor.stop_processing():
            logger.success("✅ Обработка остановлена")
            return True
        else:
            logger.warning("Обработка не была запущена")
            return False

    def get_processing_status(self) -> Dict:
        """
        Получить статус обработки

        Returns:
            Словарь со статусом системы
        """
        # Загружаем конфигурацию
        if not self.discovery.load_config():
            return {
                'error': 'Конфигурация не найдена',
                'configured': False
            }

        # Получаем информацию об эмуляторах
        all_emulators = self.discovery.get_emulators()
        enabled_emulators = self.discovery.get_enabled_emulators()

        # Получаем статус процессора
        processor_status = self.processor.get_status()

        return {
            'configured': True,
            'total_emulators': len(all_emulators),
            'enabled_emulators': len(enabled_emulators),
            'processor_running': processor_status['running'],
            'active_slots': processor_status['active_slots'],
            'max_concurrent': processor_status['max_concurrent'],
            'total_processed': processor_status['total_stats']['total_processed'],
            'total_errors': processor_status['total_stats']['failed_sessions'],
            'emulators_list': all_emulators
        }

    def get_queue_status(self) -> Dict:
        """Получить статус очереди планировщика"""
        try:
            # Получаем приоритеты из планировщика
            priorities = self.scheduler.calculate_priorities()

            return {
                'queue_size': len(priorities),
                'priorities': priorities[:10]  # Топ-10
            }
        except Exception as e:
            logger.error(f"Ошибка получения статуса очереди: {e}")
            return {
                'error': str(e),
                'queue_size': 0,
                'priorities': []
            }


# ========== ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР ORCHESTRATOR ==========

_orchestrator_instance = None


def get_orchestrator() -> Orchestrator:
    """Получение глобального экземпляра Orchestrator (паттерн Singleton)"""
    global _orchestrator_instance

    if _orchestrator_instance is None:
        _orchestrator_instance = Orchestrator()

    return _orchestrator_instance