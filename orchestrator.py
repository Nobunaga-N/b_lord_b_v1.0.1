#!/usr/bin/env python3
"""
ПРОМПТ 20: Мониторинг активных эмуляторов и освобождение слотов + CLI команды

ДОБАВЛЕНО:
✅ Детальная отчетность по ПАРАЛЛЕЛЬНОМУ прогрессу (здания И исследования)
✅ Мониторинг активных эмуляторов в реальном времени
✅ Улучшенное освобождение слотов с proper cleanup
✅ CLI команды set-speedups для зданий и исследований
✅ Статистика сессий и производительности
✅ Расширенная queue команда с приоритетами
✅ Детальный статус с ПАРАЛЛЕЛЬНЫМ прогрессом

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
    # НОВОЕ: детальная информация о прогрессе
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


class DynamicEmulatorProcessor:
    """
    🚀 ДИНАМИЧЕСКИЙ ПРОЦЕССОР ЭМУЛЯТОРОВ - ПРОМПТ 20

    НОВОЕ В ПРОМПТЕ 20:
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

        # НОВОЕ: статистика для мониторинга
        self.stats = ProcessingStats()
        self.stats_lock = threading.Lock()

        logger.info(f"Инициализирован DynamicEmulatorProcessor с {max_concurrent} слотами + мониторинг")

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

        # УЛУЧШЕНО: Ждем завершения активных задач с таймаутом
        with self.slot_lock:
            active_futures = []
            for emulator_id, slot in self.active_slots.items():
                if slot.future and not slot.future.done():
                    logger.info(f"Ждем завершения обработки эмулятора {emulator_id}")
                    active_futures.append((emulator_id, slot.future))

        # Ждем завершения с таймаутом
        for emulator_id, future in active_futures:
            try:
                future.result(timeout=30.0)  # 30 секунд на завершение
            except Exception as e:
                logger.warning(f"Эмулятор {emulator_id} завершился с ошибкой: {e}")

        # Ждем завершения основного потока
        if self.processor_thread and self.processor_thread.is_alive():
            self.processor_thread.join(timeout=5.0)

        # НОВОЕ: Очищаем все слоты при остановке
        with self.slot_lock:
            for emulator_id, slot in self.active_slots.items():
                if slot.executor:
                    slot.executor.shutdown(wait=False)
            self.active_slots.clear()

        logger.success("✅ Динамическая обработка остановлена")
        return True

    def get_status(self) -> Dict[str, Any]:
        """РАСШИРЕННЫЙ статус процессора с детальной информацией"""
        with self.slot_lock:
            active_emulators = list(self.active_slots.keys())
            active_count = len(active_emulators)

            # Детальная информация по активным слотам
            slot_details = {}
            total_buildings = 0
            total_research = 0
            total_actions = 0

            for emulator_id, slot in self.active_slots.items():
                duration = (datetime.now() - slot.start_time).total_seconds()
                slot_details[emulator_id] = {
                    'status': slot.status,
                    'duration_seconds': duration,
                    'buildings_started': slot.buildings_started,
                    'research_started': slot.research_started,
                    'actions_completed': slot.actions_completed,
                    'errors_count': len(slot.errors),
                    'last_activity': slot.last_activity.isoformat() if slot.last_activity else None
                }
                total_buildings += slot.buildings_started
                total_research += slot.research_started
                total_actions += slot.actions_completed

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
            'max_concurrent': self.max_concurrent,
            'active_slots': active_count,
            'free_slots': self.max_concurrent - active_count,
            'active_emulators': active_emulators,
            # НОВОЕ: детальная информация
            'slot_details': slot_details,
            'current_session_stats': {
                'buildings_started': total_buildings,
                'research_started': total_research,
                'actions_completed': total_actions
            },
            'total_stats': stats_dict
        }

    def get_detailed_active_emulators(self) -> List[Dict[str, Any]]:
        """НОВОЕ: Детальная информация об активных эмуляторах"""
        with self.slot_lock:
            details = []
            for emulator_id, slot in self.active_slots.items():
                # Получаем информацию об эмуляторе
                emu_info = self.orchestrator.discovery.get_emulator(emulator_id)
                if not emu_info:
                    continue

                duration = (datetime.now() - slot.start_time).total_seconds()

                # Получаем прогресс из базы данных
                try:
                    db_progress = database.get_emulator_progress(emulator_id)
                    lord_level = db_progress.get('lord_level', 0) if db_progress else 0
                    building_progress = database.get_building_progress(emulator_id)
                    research_progress = database.get_research_progress(emulator_id)
                except Exception as e:
                    logger.warning(f"Ошибка получения прогресса для эмулятора {emulator_id}: {e}")
                    lord_level = 0
                    building_progress = []
                    research_progress = []

                details.append({
                    'emulator_id': emulator_id,
                    'name': emu_info.name,
                    'status': slot.status,
                    'duration_seconds': duration,
                    'duration_formatted': self._format_duration(duration),
                    'lord_level': lord_level,
                    'progress': {
                        'buildings_started': slot.buildings_started,
                        'research_started': slot.research_started,
                        'actions_completed': slot.actions_completed,
                        'active_buildings': len([b for b in building_progress if
                                                 b.get('completion_time', datetime.now()) > datetime.now()]),
                        'active_research': len(
                            [r for r in research_progress if r.get('completion_time', datetime.now()) > datetime.now()])
                    },
                    'errors': slot.errors[-3:] if slot.errors else [],  # Последние 3 ошибки
                    'last_activity': slot.last_activity.isoformat() if slot.last_activity else None
                })

            # Сортируем по времени запуска (самые старые первыми)
            details.sort(key=lambda x: x['duration_seconds'], reverse=True)
            return details

    def reset_stats(self):
        """НОВОЕ: Сброс статистики"""
        with self.stats_lock:
            self.stats = ProcessingStats()
        logger.info("📊 Статистика обработки сброшена")

    def force_process_emulator(self, emulator_id: int, ignore_prime_time: bool = False) -> Dict[str, Any]:
        """Принудительная обработка эмулятора для тестирования"""
        logger.info(f"🧪 Принудительная обработка эмулятора {emulator_id}")

        try:
            # Получаем приоритет эмулятора
            ready_emulators = self.orchestrator.scheduler.get_ready_emulators_by_priority(1)
            priority = None

            for p in ready_emulators:
                if p.emulator_index == emulator_id:
                    priority = p
                    break

            if not priority:
                # Создаем фиктивный приоритет для тестирования
                class MockPriority:
                    def __init__(self, emu_id):
                        self.emulator_index = emu_id
                        self.total_priority = 999999
                        self.waiting_for_prime_time = False
                        self.lord_level = 10
                        self.next_check_time = datetime.now()
                        self.reasons = ['force_processing']

                priority = MockPriority(emulator_id)
                logger.warning(f"Эмулятор {emulator_id} не найден в очереди, создан mock-приоритет")

            # Проверяем прайм-тайм
            if not ignore_prime_time and priority.waiting_for_prime_time:
                return {
                    'status': 'blocked',
                    'error': 'Эмулятор ждет прайм-тайм. Используйте --ignore-prime-time'
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

    def _update_slot_status(self, emulator_id: int, status: str, **kwargs):
        """УЛУЧШЕНО: Обновление статуса слота с дополнительными данными"""
        with self.slot_lock:
            if emulator_id in self.active_slots:
                slot = self.active_slots[emulator_id]
                slot.status = status
                slot.last_activity = datetime.now()

                # Обновляем дополнительные данные
                if 'buildings_started' in kwargs:
                    slot.buildings_started += kwargs['buildings_started']
                if 'research_started' in kwargs:
                    slot.research_started += kwargs['research_started']
                if 'actions_completed' in kwargs:
                    slot.actions_completed += kwargs['actions_completed']
                if 'error' in kwargs:
                    slot.errors.append(f"{datetime.now().strftime('%H:%M:%S')}: {kwargs['error']}")

    def _processing_loop(self):
        """Основной цикл динамической обработки"""
        logger.info("🎯 Начат цикл динамической обработки")

        while self.running:
            try:
                # 0. КРИТИЧНО: Синхронизируем эмуляторы между Discovery и Database
                self._sync_emulators_to_database()

                # 1. УЛУЧШЕНО: Удаляем завершенные слоты с обновлением статистики
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

                # 3. ИСПРАВЛЕНО: Запускаем обработку готовых эмуляторов
                for priority in ready_emulators:
                    if not self.running:
                        break

                    current_free_slots = self.max_concurrent - len(self.active_slots)
                    if current_free_slots <= 0:
                        break

                    self._start_emulator_processing(priority)

                time.sleep(10.0)  # Основной интервал проверки

            except Exception as e:
                logger.error(f"❌ Ошибка в цикле обработки: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                time.sleep(30.0)  # Больше времени при ошибке

        logger.info("🏁 Цикл динамической обработки завершен")

    def _clean_completed_slots(self):
        """УЛУЧШЕНО: Очистка завершенных слотов с обновлением статистики"""
        with self.slot_lock:
            completed_slots = []

            for emulator_id, slot in list(self.active_slots.items()):
                if slot.future and slot.future.done():
                    completed_slots.append((emulator_id, slot))
                elif slot.status in ['completed', 'error']:
                    completed_slots.append((emulator_id, slot))
                elif (datetime.now() - slot.start_time).total_seconds() > 1800:  # 30 минут таймаут
                    logger.warning(f"Тайм-аут обработки эмулятора {emulator_id}")
                    completed_slots.append((emulator_id, slot))

            for emulator_id, slot in completed_slots:
                # НОВОЕ: Обновляем статистику
                self._update_stats_for_completed_slot(slot)

                # Закрываем executor
                if slot.executor:
                    slot.executor.shutdown(wait=False)

                # Удаляем слот
                del self.active_slots[emulator_id]

                duration = (datetime.now() - slot.start_time).total_seconds()
                logger.info(f"🧹 Очищен слот эмулятора {emulator_id} (статус: {slot.status}, время: {duration:.1f}с)")

    def _update_stats_for_completed_slot(self, slot: EmulatorSlot):
        """НОВОЕ: Обновление статистики при завершении слота"""
        with self.stats_lock:
            self.stats.total_processed += 1

            if slot.status == 'completed':
                self.stats.successful_sessions += 1
            else:
                self.stats.failed_sessions += 1

            self.stats.total_buildings_started += slot.buildings_started
            self.stats.total_research_started += slot.research_started
            self.stats.total_actions_completed += slot.actions_completed

            # Обновляем среднее время обработки
            duration = (datetime.now() - slot.start_time).total_seconds()
            total_time = self.stats.average_processing_time * (self.stats.total_processed - 1) + duration
            self.stats.average_processing_time = total_time / self.stats.total_processed

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
                # ИСПРАВЛЕНИЕ: Запускаем эмулятор и ждем готовности ADB
                success = self.orchestrator.ldconsole.start_emulator(emulator_id)
                if not success:
                    error_msg = f"Не удалось запустить эмулятор {emulator_id}"
                    logger.error(error_msg)
                    self._update_slot_status(emulator_id, 'error', error=error_msg)
                    return {'status': 'error', 'error': error_msg}

                # КРИТИЧНО: Правильное ожидание готовности ADB
                logger.info(f"Ожидание готовности ADB для эмулятора {emulator_id}...")
                if not self._wait_for_adb_ready(emulator_id):
                    error_msg = f"ADB не готов для эмулятора {emulator_id}"
                    logger.error(error_msg)
                    self._update_slot_status(emulator_id, 'error', error=error_msg)
                    return {'status': 'error', 'error': error_msg}

                logger.success(f"✅ Эмулятор {emulator_id} запущен и готов")
            else:
                logger.info(f"Эмулятор {emulator_id} уже запущен")

            # ЭТАП 2: ПАРАЛЛЕЛЬНАЯ обработка игры
            self._update_slot_status(emulator_id, 'processing_game')
            logger.info(f"🎮 ПАРАЛЛЕЛЬНАЯ обработка игры для эмулятора {emulator_id}")

            # ЗДЕСЬ БУДЕТ ИНТЕГРАЦИЯ С bot_worker.py (промпт 21)
            # Пока симулируем ПАРАЛЛЕЛЬНУЮ работу
            processing_result = self._simulate_parallel_game_processing(emulator_id)

            # Обновляем статистику слота
            self._update_slot_status(
                emulator_id,
                'completed',
                buildings_started=processing_result.get('buildings_started', 0),
                research_started=processing_result.get('research_started', 0),
                actions_completed=processing_result.get('actions_completed', 0)
            )

            # ЭТАП 3: Остановка эмулятора
            self._update_slot_status(emulator_id, 'stopping_emulator')
            logger.info(f"Остановка эмулятора {emulator_id}...")

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

    def _wait_for_adb_ready(self, emulator_id: int, max_wait: int = 90) -> bool:
        """ИСПРАВЛЕНО: Ожидание готовности ADB с детальной диагностикой"""
        logger.info(f"⏳ Ожидание готовности ADB для эмулятора {emulator_id} (макс {max_wait}с)")

        start_time = datetime.now()
        last_status_log = start_time

        while (datetime.now() - start_time).total_seconds() < max_wait:
            # Проверяем статус каждые 10 секунд
            if (datetime.now() - last_status_log).total_seconds() >= 10:
                elapsed = (datetime.now() - start_time).total_seconds()
                logger.info(f"🔍 Проверка ADB эмулятора {emulator_id} - прошло {elapsed:.0f}с")
                last_status_log = datetime.now()

            if self.orchestrator.ldconsole.is_adb_ready(emulator_id):
                total_time = (datetime.now() - start_time).total_seconds()
                logger.success(f"✅ ADB готов для эмулятора {emulator_id} за {total_time:.1f}с")
                return True

            time.sleep(5.0)  # Проверяем каждые 5 секунд

        total_time = (datetime.now() - start_time).total_seconds()
        logger.error(f"❌ Таймаут ожидания ADB для эмулятора {emulator_id} ({total_time:.1f}с)")
        return False

    def _simulate_parallel_game_processing(self, emulator_id: int) -> Dict[str, Any]:
        """ВРЕМЕННАЯ симуляция ПАРАЛЛЕЛЬНОЙ обработки игры (до промпта 21)"""
        logger.info(f"🎮 СИМУЛЯЦИЯ ПАРАЛЛЕЛЬНОЙ обработки игры для эмулятора {emulator_id}")

        # Симулируем ПАРАЛЛЕЛЬНУЮ работу зданий И исследований
        time.sleep(5.0)  # Симуляция работы

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
                database.sync_emulator(
                    emulator_index=emu_index,
                    emulator_name=emu_info.name,
                    enabled=emu_info.enabled,
                    notes=emu_info.notes
                )
        except Exception as e:
            logger.warning(f"Ошибка синхронизации эмуляторов: {e}")

    def _format_duration(self, seconds: float) -> str:
        """НОВОЕ: Форматирование длительности в читаемый вид"""
        if seconds < 60:
            return f"{seconds:.0f}с"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            return f"{minutes:.0f}м {secs:.0f}с"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours:.0f}ч {minutes:.0f}м"


class Orchestrator:
    """
    🎯 КАРДИНАЛЬНО ПЕРЕРАБОТАННЫЙ ORCHESTRATOR

    Интегрирует все компоненты системы:
    - EmulatorDiscovery (автообнаружение)
    - SmartLDConsole (управление эмуляторами)
    - SmartScheduler (умное планирование)
    - DynamicEmulatorProcessor (динамическая обработка)
    - PrimeTimeManager (система прайм-таймов)
    """

    def __init__(self):
        logger.info("🚀 Инициализация кардинально переработанного Orchestrator...")

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
    """Beast Lord Bot - Кардинально переработанный Orchestrator v2.0 + ПРОМПТ 20"""
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


def _show_emulators_list(enabled_only: bool, disabled_only: bool, detailed: bool):
    """Вспомогательная функция для отображения списка эмуляторов"""
    orchestrator = get_orchestrator()

    if enabled_only:
        emulators = orchestrator.discovery.get_enabled_emulators()
        title = "ВКЛЮЧЕННЫЕ ЭМУЛЯТОРЫ"
    elif disabled_only:
        emulators = orchestrator.discovery.get_disabled_emulators()
        title = "ВЫКЛЮЧЕННЫЕ ЭМУЛЯТОРЫ"
    else:
        emulators = orchestrator.discovery.get_emulators()
        title = "ВСЕ ЭМУЛЯТОРЫ"

    logger.info(f"=== {title} ===")

    if not emulators:
        logger.info("Эмуляторы не найдены")
        return

    for idx, emu in emulators.items():
        status_icon = "✅" if emu.enabled else "❌"
        running_status = "🟢" if orchestrator.ldconsole.is_running(idx) else "🔴"

        if detailed:
            logger.info(f"{status_icon} ID {idx}: {emu.name}")
            logger.info(f"   Порт ADB: {emu.adb_port}")
            logger.info(
                f"   Статус: {running_status} {'Запущен' if orchestrator.ldconsole.is_running(idx) else 'Остановлен'}")
            logger.info(f"   Заметки: {emu.notes}")
            logger.info("")
        else:
            logger.info(f"{status_icon} {running_status} ID {idx}: {emu.name} (порт {emu.adb_port}) - {emu.notes}")


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
        orchestrator.discovery.save_config()
        logger.success(f"Заметка для эмулятора {emulator_id} обновлена")
    else:
        logger.error(f"Не удалось обновить заметку для эмулятора {emulator_id}")
        sys.exit(1)


# ========== НОВЫЕ КОМАНДЫ ДИНАМИЧЕСКОЙ ОБРАБОТКИ + ПРОМПТ 20 ==========

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
@click.option('--active-emulators', is_flag=True, help='Показать детали активных эмуляторов')
def status(detailed: bool, active_emulators: bool):
    """РАСШИРЕННЫЙ статус системы и динамической обработки с ПАРАЛЛЕЛЬНЫМ прогрессом"""
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

    # НОВОЕ: Расширенный статус динамической обработки
    processor_status = orchestrator.processor.get_status()
    logger.info(f"\n🔄 ДИНАМИЧЕСКАЯ ОБРАБОТКА:")
    logger.info(f"Статус: {'🟢 Запущена' if processor_status['running'] else '🔴 Остановлена'}")
    logger.info(f"Активных слотов: {processor_status['active_slots']}/{processor_status['max_concurrent']}")
    logger.info(f"Свободных слотов: {processor_status['free_slots']}")

    if processor_status['active_emulators']:
        logger.info(f"Активные эмуляторы: {processor_status['active_emulators']}")

    # НОВОЕ: Статистика текущей сессии
    current_stats = processor_status['current_session_stats']
    logger.info(f"\n📈 ТЕКУЩАЯ СЕССИЯ:")
    logger.info(f"Зданий начато: {current_stats['buildings_started']}")
    logger.info(f"Исследований начато: {current_stats['research_started']}")
    logger.info(f"Действий выполнено: {current_stats['actions_completed']}")

    # НОВОЕ: Общая статистика
    if detailed:
        total_stats = processor_status['total_stats']
        logger.info(f"\n📊 ОБЩАЯ СТАТИСТИКА:")
        logger.info(f"Всего обработано: {total_stats['total_processed']}")
        logger.info(f"Успешно: {total_stats['successful_sessions']}")
        logger.info(f"С ошибками: {total_stats['failed_sessions']}")
        logger.info(f"Всего зданий: {total_stats['total_buildings_started']}")
        logger.info(f"Всего исследований: {total_stats['total_research_started']}")
        logger.info(f"Всего действий: {total_stats['total_actions_completed']}")
        if total_stats['average_processing_time'] > 0:
            logger.info(f"Среднее время обработки: {total_stats['average_processing_time']:.1f}с")

    # НОВОЕ: Детали активных эмуляторов
    if active_emulators and processor_status['active_emulators']:
        logger.info(f"\n🎯 АКТИВНЫЕ ЭМУЛЯТОРЫ:")
        active_details = orchestrator.processor.get_detailed_active_emulators()

        for detail in active_details:
            logger.info(f"\n📱 Эмулятор {detail['emulator_id']}: {detail['name']}")
            logger.info(f"   Статус: {detail['status']}")
            logger.info(f"   Время работы: {detail['duration_formatted']}")
            logger.info(f"   Уровень лорда: {detail['lord_level']}")

            progress = detail['progress']
            logger.info(f"   Прогресс:")
            logger.info(f"     🏗️ Зданий начато: {progress['buildings_started']}")
            logger.info(f"     🔬 Исследований начато: {progress['research_started']}")
            logger.info(f"     🎯 Действий выполнено: {progress['actions_completed']}")
            logger.info(f"     📊 Активно строится: {progress['active_buildings']}")
            logger.info(f"     📊 Активно исследуется: {progress['active_research']}")

            if detail['errors']:
                logger.warning(f"   ⚠️ Последние ошибки: {'; '.join(detail['errors'])}")

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
    if summary['enabled'] > 0 and not active_emulators:
        logger.info(f"\n✅ ВКЛЮЧЕННЫЕ ЭМУЛЯТОРЫ:")
        enabled = orchestrator.discovery.get_enabled_emulators()
        for idx, emu in enabled.items():
            running_status = "🟢" if orchestrator.ldconsole.is_running(idx) else "🔴"
            logger.info(f"  {running_status} ID {idx}: {emu.name} (порт {emu.adb_port}) - {emu.notes}")


@cli.command()
@click.option('--max-concurrent', default=5, help='Максимум эмуляторов в очереди')
@click.option('--show-blocked', is_flag=True, help='Показать заблокированные эмуляторы')
def queue(max_concurrent: int, show_blocked: bool):
    """РАСШИРЕННАЯ очередь эмуляторов по приоритету с ПАРАЛЛЕЛЬНЫМ прогрессом"""
    logger.info(f"=== ОЧЕРЕДЬ ЭМУЛЯТОРОВ (макс {max_concurrent}) ===")
    orchestrator = get_orchestrator()

    # Получаем готовых эмуляторов по приоритету
    ready_emulators = orchestrator.scheduler.get_ready_emulators_by_priority(max_concurrent)

    if not ready_emulators:
        logger.info("Нет эмуляторов готовых к обработке")

        # НОВОЕ: Показываем причины блокировки
        if show_blocked:
            logger.info("\n🔍 Анализ заблокированных эмуляторов...")
            try:
                all_emulators = database.get_all_emulators(enabled_only=True)
                blocked_count = 0

                for emu in all_emulators:
                    emulator_id = emu['emulator_index']
                    priority = orchestrator.scheduler.calculate_priority(emulator_id)

                    if priority.next_check_time > datetime.now():
                        blocked_count += 1
                        time_left = (priority.next_check_time - datetime.now()).total_seconds()
                        logger.info(f"🔒 Эмулятор {emulator_id}: ждет {time_left / 60:.0f}мин")

                if blocked_count == 0:
                    logger.info("✅ Нет заблокированных эмуляторов")

            except Exception as e:
                logger.warning(f"Ошибка анализа заблокированных эмуляторов: {e}")

        return

    logger.info(f"Готовых к обработке: {len(ready_emulators)}")

    for i, priority in enumerate(ready_emulators, 1):
        emulator_id = priority.emulator_index

        # Получаем информацию об эмуляторе
        emu_info = orchestrator.discovery.get_emulator(emulator_id)
        emu_name = emu_info.name if emu_info else f"Эмулятор_{emulator_id}"

        # НОВОЕ: Получаем прогресс зданий и исследований
        try:
            building_progress = database.get_building_progress(emulator_id)
            research_progress = database.get_research_progress(emulator_id)

            active_buildings = len(
                [b for b in building_progress if b.get('completion_time', datetime.now()) > datetime.now()])
            active_research = len(
                [r for r in research_progress if r.get('completion_time', datetime.now()) > datetime.now()])

        except Exception as e:
            logger.warning(f"Ошибка получения прогресса для эмулятора {emulator_id}: {e}")
            active_buildings = 0
            active_research = 0

        logger.info(f"\n{i}. 🎯 Эмулятор {emulator_id}: {emu_name}")
        logger.info(f"   Приоритет: {priority.total_priority}")
        logger.info(f"   Уровень лорда: {priority.lord_level}")
        logger.info(f"   Активно строится: 🏗️ {active_buildings} | 🔬 {active_research}")

        if priority.waiting_for_prime_time:
            logger.warning(f"   ⏰ Ждет прайм-тайм")

        if priority.reasons:
            logger.info(f"   Причины: {', '.join(priority.reasons)}")


@cli.command('reset-stats')
def reset_stats():
    """НОВОЕ: Сброс статистики обработки"""
    logger.info("=== СБРОС СТАТИСТИКИ ===")
    orchestrator = get_orchestrator()

    orchestrator.processor.reset_stats()
    logger.success("✅ Статистика обработки сброшена")


@cli.command('monitor')
@click.option('--interval', default=30, help='Интервал обновления в секундах')
@click.option('--count', default=0, help='Количество обновлений (0 = бесконечно)')
def monitor(interval: int, count: int):
    """НОВОЕ: Мониторинг активных эмуляторов в реальном времени"""
    logger.info(f"=== МОНИТОРИНГ АКТИВНЫХ ЭМУЛЯТОРОВ (обновление каждые {interval}с) ===")
    orchestrator = get_orchestrator()

    iteration = 0
    try:
        while count == 0 or iteration < count:
            iteration += 1

            # Очищаем экран (опционально)
            # print("\033[2J\033[H", end="")

            current_time = datetime.now().strftime("%H:%M:%S")
            logger.info(f"\n🔄 Обновление #{iteration} - {current_time}")

            # Получаем статус
            processor_status = orchestrator.processor.get_status()

            if processor_status['running']:
                logger.info(
                    f"🟢 Обработка запущена - {processor_status['active_slots']}/{processor_status['max_concurrent']} слотов")

                if processor_status['active_emulators']:
                    active_details = orchestrator.processor.get_detailed_active_emulators()

                    for detail in active_details:
                        progress = detail['progress']
                        logger.info(
                            f"  📱 {detail['emulator_id']}: {detail['status']} | {detail['duration_formatted']} | 🏗️{progress['buildings_started']} 🔬{progress['research_started']} 🎯{progress['actions_completed']}")
                else:
                    logger.info("  ⏳ Нет активных эмуляторов")
            else:
                logger.info("🔴 Обработка остановлена")

            if count == 0 or iteration < count:
                time.sleep(interval)

    except KeyboardInterrupt:
        logger.info("\n⏹️ Мониторинг остановлен")


# ========== НОВЫЕ CLI КОМАНДЫ УПРАВЛЕНИЯ УСКОРЕНИЯМИ ==========

@cli.command('set-speedups')
@click.option('--id', 'emulator_id', required=True, type=int, help='ID эмулятора')
@click.option('--building', required=True, help='Название здания')
@click.option('--enabled', type=bool, required=True, help='Включить/выключить ускорения')
def set_speedups(emulator_id: int, building: str, enabled: bool):
    """НОВОЕ: Управление ускорениями зданий"""
    logger.info(f"=== УПРАВЛЕНИЕ УСКОРЕНИЯМИ ЗДАНИЙ ===")
    logger.info(f"Эмулятор {emulator_id}, здание '{building}', ускорения: {'включены' if enabled else 'выключены'}")

    try:
        # Обновляем настройки ускорений в БД
        database.set_building_speedup(emulator_id, building, enabled)
        logger.success(
            f"✅ Ускорения для здания '{building}' на эмуляторе {emulator_id} {'включены' if enabled else 'выключены'}")

    except Exception as e:
        logger.error(f"❌ Ошибка обновления настроек ускорений: {e}")
        sys.exit(1)


@cli.command('set-research-speedups')
@click.option('--id', 'emulator_id', required=True, type=int, help='ID эмулятора')
@click.option('--research', required=True, help='Название исследования')
@click.option('--enabled', type=bool, required=True, help='Включить/выключить ускорения')
def set_research_speedups(emulator_id: int, research: str, enabled: bool):
    """НОВОЕ: Управление ускорениями исследований"""
    logger.info(f"=== УПРАВЛЕНИЕ УСКОРЕНИЯМИ ИССЛЕДОВАНИЙ ===")
    logger.info(
        f"Эмулятор {emulator_id}, исследование '{research}', ускорения: {'включены' if enabled else 'выключены'}")

    try:
        # Обновляем настройки ускорений в БД
        database.set_research_speedup(emulator_id, research, enabled)
        logger.success(
            f"✅ Ускорения для исследования '{research}' на эмуляторе {emulator_id} {'включены' if enabled else 'выключены'}")

    except Exception as e:
        logger.error(f"❌ Ошибка обновления настроек ускорений: {e}")
        sys.exit(1)


@cli.command('show-speedups')
@click.option('--id', 'emulator_id', type=int, help='ID эмулятора (все, если не указан)')
def show_speedups(emulator_id: Optional[int]):
    """НОВОЕ: Показать текущие настройки ускорений"""
    logger.info("=== НАСТРОЙКИ УСКОРЕНИЙ ===")

    try:
        if emulator_id:
            logger.info(f"Настройки для эмулятора {emulator_id}:")
            # Получаем настройки ускорений из прогресса зданий и исследований
            building_progress = database.get_building_progress(emulator_id)
            research_progress = database.get_research_progress(emulator_id)
        else:
            logger.info("Настройки для всех эмуляторов:")
            # Получаем все настройки ускорений
            building_progress = []
            research_progress = []
            emulators = database.get_all_emulators()
            for emu in emulators:
                building_progress.extend(database.get_building_progress(emu['emulator_index']))
                research_progress.extend(database.get_research_progress(emu['emulator_index']))

        if building_progress:
            logger.info("\n🏗️ УСКОРЕНИЯ ЗДАНИЙ:")
            for building in building_progress:
                if building.get('use_speedups') is not None:
                    status = "✅" if building['use_speedups'] else "❌"
                    logger.info(f"  {status} Эмулятор {building['emulator_id']}: {building['building_name']}")

        if research_progress:
            logger.info("\n🔬 УСКОРЕНИЯ ИССЛЕДОВАНИЙ:")
            for research in research_progress:
                if research.get('use_speedups') is not None:
                    status = "✅" if research['use_speedups'] else "❌"
                    logger.info(f"  {status} Эмулятор {research['emulator_id']}: {research['research_name']}")

        if not building_progress and not research_progress:
            logger.info("Настройки ускорений не найдены")

    except Exception as e:
        logger.error(f"❌ Ошибка получения настроек ускорений: {e}")
        sys.exit(1)


# ========== СУЩЕСТВУЮЩИЕ КОМАНДЫ ==========

@cli.command('force-process')
@click.option('--id', 'emulator_id', required=True, type=int, help='ID эмулятора')
@click.option('--ignore-prime-time', is_flag=True, help='Игнорировать ожидание прайм-тайма')
def force_process(emulator_id: int, ignore_prime_time: bool):
    """Принудительная обработка эмулятора (для тестирования)"""
    logger.info(f"=== ПРИНУДИТЕЛЬНАЯ ОБРАБОТКА ЭМУЛЯТОРА {emulator_id} ===")
    orchestrator = get_orchestrator()

    # Проверяем что эмулятор существует и включен
    if not orchestrator.discovery.load_config():
        logger.error("Конфигурация не найдена. Выполните сначала 'scan'")
        sys.exit(1)

    emu_info = orchestrator.discovery.get_emulator_info(emulator_id)
    if not emu_info:
        logger.error(f"Эмулятор {emulator_id} не найден")
        sys.exit(1)

    if not emu_info.enabled:
        logger.error(f"Эмулятор {emulator_id} выключен. Включите его командой 'enable'")
        sys.exit(1)

    logger.info(f"Принудительная обработка эмулятора {emulator_id}: {emu_info.name}")
    if ignore_prime_time:
        logger.warning("⚠️ Игнорирование прайм-таймов включено")

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
            logger.info(f"   {i}. Эмулятор {priority.emulator_index} (приоритет {priority.total_priority})")
    except Exception as e:
        logger.error(f"❌ Ошибка работы с планировщиком: {e}")
        return

    # НОВОЕ: Проверяем статистику процессора
    try:
        processor_status = orchestrator.processor.get_status()
        logger.info(f"\n🔄 DynamicEmulatorProcessor:")
        logger.info(f"   Запущен: {processor_status['running']}")
        logger.info(f"   Активных слотов: {processor_status['active_slots']}")
        logger.info(f"   Общая статистика: {processor_status['total_stats']}")
    except Exception as e:
        logger.error(f"❌ Ошибка процессора: {e}")

    logger.success("✅ Отладочная информация собрана")


if __name__ == '__main__':
    cli()