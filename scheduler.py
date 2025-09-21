"""
SmartScheduler для Beast Lord Bot - ПРОМПТ 18 ЗАВЕРШЕН
Умный планировщик с ПАРАЛЛЕЛЬНЫМ планированием зданий И исследований

КРИТИЧНО: Методы для ПАРАЛЛЕЛЬНОГО планирования:
- calculate_priority() с множественными факторами (включая свободные слоты)
- get_ready_emulators_by_priority() - готовые эмуляторы по приоритету
- calculate_next_check_time() с умной логикой для завершения зданий И исследований
- Интеграция с прайм-таймами и ПАРАЛЛЕЛЬНЫМ прогрессом

ОСОБЕННОСТИ:
- Готовность к повышению лорда = высший приоритет (1000 баллов)
- Завершенные строительства/исследования = высокий приоритет (500 баллов)
- Свободные слоты строительства/исследований = средний приоритет (200 баллов)
- Прайм-тайм для нужных действий = бонус (+100 баллов)
- Время с последней обработки = базовый приоритет (+1 за час)
"""

import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field

from loguru import logger
from utils.prime_time_manager import PrimeTimeManager
from utils.database import Database


@dataclass
class EmulatorPriority:
    """Класс для хранения приоритета эмулятора с детальной информацией"""
    emulator_id: int
    emulator_index: int
    emulator_name: str
    lord_level: int
    total_priority: int = 0
    priority_factors: Dict[str, int] = field(default_factory=dict)
    next_check_time: Optional[datetime] = None
    waiting_for_prime_time: bool = False
    next_prime_time_window: Optional[datetime] = None
    recommended_actions: List[str] = field(default_factory=list)

    def __str__(self):
        return (f"EmulatorPriority(index={self.emulator_index}, "
                f"priority={self.total_priority}, lord={self.lord_level})")


class SmartScheduler:
    """
    Умный планировщик с интеграцией прайм-таймов и ПАРАЛЛЕЛЬНЫМ планированием

    ОСНОВНЫЕ ВОЗМОЖНОСТИ:
    - Расчет приоритетов с множественными факторами
    - Учет свободных слотов строительства И исследований ПАРАЛЛЕЛЬНО
    - Умное планирование времени к завершению зданий/исследований
    - Интеграция с системой прайм-таймов
    - Динамическая обработка по готовности
    """

    def __init__(self, database: Database, prime_time_manager: Optional[PrimeTimeManager] = None):
        """
        Инициализация умного планировщика

        Args:
            database: Экземпляр базы данных
            prime_time_manager: Менеджер прайм-таймов (создается автоматически если None)
        """
        self.database = database
        self.prime_time_manager = prime_time_manager or PrimeTimeManager()

        # Настройки приоритетов из ТЗ - КРИТИЧНО!
        self.priority_weights = {
            'lord_upgrade_ready': 1000,  # Готовность к повышению лорда = ВЫСШИЙ приоритет
            'completed_buildings': 500,  # Завершенные строительства = высокий приоритет
            'completed_research': 500,   # Завершенные исследования = высокий приоритет
            'free_builder_slot': 200,    # Свободный слот строительства = средний приоритет
            'free_research_slot': 200,   # Свободный слот исследований = средний приоритет
            'prime_time_bonus': 100,     # Бонус за прайм-тайм = бонус приоритета
            'per_hour_waiting': 1,       # За каждый час ожидания = базовый приоритет
        }

        # Минимальные интервалы по уровню лорда (из ТЗ) - КРИТИЧНО!
        self.min_check_intervals = {
            'lord_10_12': timedelta(minutes=5),   # 5 минут для быстрых действий
            'lord_13_15': timedelta(minutes=30),  # 30 минут для средних действий
            'lord_16_18': timedelta(hours=1),     # 1 час для долгих действий
            'lord_19_plus': timedelta(hours=4),   # 4 часа для фарма
        }

        # Настройки прайм-таймов
        self.prime_time_settings = {
            'max_wait_hours': 2.0,       # Максимум ждать прайм-тайм
            'check_interval': 300,       # Проверка каждые 5 минут
            'completion_buffer': 120,    # +2 минуты к завершению
        }

        logger.info("🧠 SmartScheduler инициализирован с ПАРАЛЛЕЛЬНЫМ планированием")

    def calculate_emulator_priority(self, emulator_data: Dict[str, Any]) -> EmulatorPriority:
        """
        КРИТИЧНО: Расчет приоритета эмулятора с множественными факторами
        Включая свободные слоты строительства И исследований

        Args:
            emulator_data: Данные эмулятора из БД

        Returns:
            Объект EmulatorPriority с детальным расчетом приоритета
        """
        priority = EmulatorPriority(
            emulator_id=emulator_data['id'],
            emulator_index=emulator_data['emulator_index'],
            emulator_name=emulator_data['emulator_name'],
            lord_level=emulator_data['lord_level']
        )

        logger.debug(f"🔍 Расчет приоритета для эмулятора {priority.emulator_index}")

        # 1. ГОТОВНОСТЬ К ПОВЫШЕНИЮ ЛОРДА = ВЫСШИЙ приоритет (1000 баллов)
        if emulator_data.get('ready_for_lord_upgrade', False):
            bonus = self.priority_weights['lord_upgrade_ready']
            priority.priority_factors['lord_upgrade_ready'] = bonus
            priority.recommended_actions.append('upgrade_lord')
            logger.debug(f"   ⭐ Готов к повышению лорда (+{bonus})")

        # 2. ЗАВЕРШЕННЫЕ СТРОИТЕЛЬСТВА И ИССЛЕДОВАНИЯ = высокий приоритет (500 баллов)
        completed_buildings = self.database.get_completed_buildings(emulator_data['id'])
        completed_research = self.database.get_completed_research(emulator_data['id'])

        if completed_buildings:
            count = len(completed_buildings)
            bonus = self.priority_weights['completed_buildings'] * count
            priority.priority_factors['completed_buildings'] = bonus
            priority.recommended_actions.extend(
                [f"complete_building_{b['building_name']}" for b in completed_buildings])
            logger.debug(f"   🏗️ {count} завершенных зданий (+{bonus})")

        if completed_research:
            count = len(completed_research)
            bonus = self.priority_weights['completed_research'] * count
            priority.priority_factors['completed_research'] = bonus
            priority.recommended_actions.extend(
                [f"complete_research_{r['research_name']}" for r in completed_research])
            logger.debug(f"   🔬 {count} завершенных исследований (+{bonus})")

        # 3. СВОБОДНЫЕ СЛОТЫ СТРОИТЕЛЬСТВА И ИССЛЕДОВАНИЙ = средний приоритет (200 баллов)
        # КРИТИЧНО: ПАРАЛЛЕЛЬНАЯ проверка слотов
        free_building_slots = self._get_free_building_slots(emulator_data)
        free_research_slots = self._get_free_research_slots(emulator_data)

        if free_building_slots > 0:
            # Проверяем есть ли что строить
            available_buildings = self.database.get_buildings_ready_for_upgrade(emulator_data['id'])
            if available_buildings:
                bonus = self.priority_weights['free_builder_slot'] * free_building_slots
                priority.priority_factors['free_builder_slot'] = bonus
                priority.recommended_actions.append('start_building')
                logger.debug(f"   🔨 {free_building_slots} свободных слотов строительства (+{bonus})")

        if free_research_slots > 0:
            # Проверяем есть ли что исследовать
            available_research = self.database.get_available_research_for_upgrade(emulator_data['id'])
            if available_research:
                bonus = self.priority_weights['free_research_slot'] * free_research_slots
                priority.priority_factors['free_research_slot'] = bonus
                priority.recommended_actions.append('start_research')
                logger.debug(f"   📚 {free_research_slots} свободных слотов исследований (+{bonus})")

        # 4. ПРАЙМ-ТАЙМ БОНУС = бонус приоритета (+100 баллов)
        prime_time_bonus = self._calculate_prime_time_bonus(priority.recommended_actions)
        if prime_time_bonus > 0:
            priority.priority_factors['prime_time_bonus'] = prime_time_bonus
            logger.debug(f"   🎯 Прайм-тайм активен (+{prime_time_bonus})")

        # 5. ВРЕМЯ С ПОСЛЕДНЕЙ ОБРАБОТКИ = базовый приоритет (+1 за час)
        waiting_bonus = self._calculate_waiting_bonus(emulator_data)
        if waiting_bonus > 0:
            priority.priority_factors['per_hour_waiting'] = waiting_bonus
            logger.debug(f"   ⏰ Время ожидания (+{waiting_bonus})")

        # Суммарный приоритет
        priority.total_priority = sum(priority.priority_factors.values())

        # Расчет времени следующей проверки с УМНОЙ логикой
        priority.next_check_time = self._calculate_next_check_time(emulator_data)

        # Проверка на ожидание прайм-тайма
        prime_wait_result = self._should_wait_for_prime_time(priority.recommended_actions)
        if prime_wait_result:
            should_wait, next_prime_time = prime_wait_result
            priority.waiting_for_prime_time = should_wait
            priority.next_prime_time_window = next_prime_time

        logger.debug(f"   💯 Итого приоритет: {priority.total_priority}")
        return priority

    def get_ready_emulators_by_priority(self, max_concurrent: int = 5) -> List[EmulatorPriority]:
        """
        КРИТИЧНО: Получение готовых к обработке эмуляторов, отсортированных по приоритету
        Основа динамической обработки по готовности

        Args:
            max_concurrent: Максимальное количество одновременно обрабатываемых эмуляторов

        Returns:
            Список эмуляторов готовых к обработке (до max_concurrent), отсортированных по приоритету
        """
        logger.info("🎯 Определяем приоритеты готовых эмуляторов...")

        # Получаем включенные эмуляторы
        enabled_emulators = self.database.get_all_emulators(enabled_only=True)
        current_time = datetime.now()

        ready_emulators = []

        for emulator_data in enabled_emulators:
            # Проверяем можно ли обрабатывать эмулятор сейчас
            if not self._is_emulator_ready_for_processing(emulator_data, current_time):
                continue

            # Рассчитываем приоритет
            priority = self.calculate_emulator_priority(emulator_data)

            # Если эмулятор ждет прайм-тайм и до него больше лимита - пропускаем
            if priority.waiting_for_prime_time and priority.next_prime_time_window:
                wait_hours = (priority.next_prime_time_window - current_time).total_seconds() / 3600
                if wait_hours > self.prime_time_settings['max_wait_hours']:
                    logger.debug(
                        f"⏳ Эмулятор {priority.emulator_index}: слишком долго ждать прайм-тайм ({wait_hours:.1f}ч)")
                    continue

            ready_emulators.append(priority)

        # Сортируем по приоритету (убывание) - КРИТИЧНО!
        ready_emulators.sort(key=lambda x: x.total_priority, reverse=True)

        # Ограничиваем количество
        result = ready_emulators[:max_concurrent]

        logger.info(f"📊 Готово к обработке: {len(result)} из {len(enabled_emulators)} включенных эмуляторов")

        for i, priority in enumerate(result, 1):
            logger.info(f"   {i}. Приоритет {priority.total_priority}: эмулятор {priority.emulator_index} "
                        f"({priority.emulator_name}, лорд {priority.lord_level})")

        return result

    def _calculate_next_check_time(self, emulator_data: Dict[str, Any]) -> datetime:
        """
        КРИТИЧНО: Умный расчет времени следующей проверки эмулятора
        С логикой для завершения зданий И исследований ПАРАЛЛЕЛЬНО

        Args:
            emulator_data: Данные эмулятора

        Returns:
            Время следующей проверки (к завершению ± минимальный интервал)
        """
        current_time = datetime.now()
        lord_level = emulator_data['lord_level']

        # 1. Получаем минимальный интервал для уровня лорда
        min_interval = self._get_min_interval_for_lord_level(lord_level)

        # 2. Получаем активные строительства И исследования ПАРАЛЛЕЛЬНО
        active_buildings = self.database.get_active_buildings(emulator_data['id'])
        active_research = self.database.get_active_research(emulator_data['id'])

        all_active = []

        # Парсим времена завершения зданий
        for building in active_buildings:
            if building.get('estimated_completion'):
                try:
                    completion_time = datetime.fromisoformat(building['estimated_completion'])
                    all_active.append(completion_time)
                except (ValueError, TypeError):
                    continue

        # Парсим времена завершения исследований
        for research in active_research:
            if research.get('estimated_completion'):
                try:
                    completion_time = datetime.fromisoformat(research['estimated_completion'])
                    all_active.append(completion_time)
                except (ValueError, TypeError):
                    continue

        if all_active:
            # Находим ближайшее завершение (здание ИЛИ исследование)
            next_completion = min(all_active)
            buffer_time = timedelta(seconds=self.prime_time_settings['completion_buffer'])
            optimal_time = next_completion + buffer_time

            # Проверяем минимальный интервал
            last_processed = emulator_data.get('last_processed')
            if last_processed:
                try:
                    last_time = datetime.fromisoformat(last_processed)
                    earliest_allowed = last_time + min_interval

                    # Берем максимум из оптимального времени и минимально разрешенного
                    next_check = max(optimal_time, earliest_allowed)
                except (ValueError, TypeError):
                    next_check = optimal_time
            else:
                next_check = optimal_time

            logger.debug(
                f"⏰ Эмулятор {emulator_data['emulator_index']}: следующая проверка к завершению {next_check.strftime('%H:%M')}")
            return next_check
        else:
            # Нет активных действий - зайти как можно скорее (но не раньше мин интервала)
            last_processed = emulator_data.get('last_processed')
            if last_processed:
                try:
                    last_time = datetime.fromisoformat(last_processed)
                    next_check = last_time + min_interval
                except (ValueError, TypeError):
                    next_check = current_time + min_interval
            else:
                next_check = current_time + min_interval

            logger.debug(
                f"⚡ Эмулятор {emulator_data['emulator_index']}: нет активных действий, следующая проверка {next_check.strftime('%H:%M')}")
            return next_check

    def _get_min_interval_for_lord_level(self, lord_level: int) -> timedelta:
        """Получение минимального интервала для уровня лорда"""
        if lord_level <= 12:
            return self.min_check_intervals['lord_10_12']
        elif lord_level <= 15:
            return self.min_check_intervals['lord_13_15']
        elif lord_level <= 18:
            return self.min_check_intervals['lord_16_18']
        else:
            return self.min_check_intervals['lord_19_plus']

    def _get_free_building_slots(self, emulator_data: Dict[str, Any]) -> int:
        """
        КРИТИЧНО: Получение количества свободных слотов строительства
        ПАРАЛЛЕЛЬНО с исследованиями
        """
        lord_level = emulator_data['lord_level']

        # Количество слотов строительства зависит от уровня лорда (из ТЗ)
        if lord_level <= 15:
            max_slots = 3  # 3 строителя для лордов 10-15
        else:
            max_slots = 4  # 4 строителя для лордов 16+

        # Получаем активные строительства
        active_buildings = self.database.get_active_buildings(emulator_data['id'])
        used_slots = len(active_buildings)

        return max(0, max_slots - used_slots)

    def _get_free_research_slots(self, emulator_data: Dict[str, Any]) -> int:
        """
        КРИТИЧНО: Получение количества свободных слотов исследований
        ПАРАЛЛЕЛЬНО с строительством (отдельная очередь)
        """
        # Исследования: отдельная очередь (обычно 1 слот)
        max_slots = 1

        # Получаем активные исследования
        active_research = self.database.get_active_research(emulator_data['id'])
        used_slots = len(active_research)

        return max(0, max_slots - used_slots)

    def _calculate_prime_time_bonus(self, recommended_actions: List[str]) -> int:
        """
        Расчет бонуса приоритета за прайм-тайм

        Args:
            recommended_actions: Список рекомендуемых действий

        Returns:
            Бонус приоритета (+100 за прайм-тайм)
        """
        if not recommended_actions:
            return 0

        # Определяем типы действий для прайм-тайма
        action_types = []
        for action in recommended_actions:
            if 'building' in action:
                action_types.append('building_power')
            elif 'research' in action or 'evolution' in action:
                action_types.append('evolution_bonus')
            elif 'lord' in action:
                action_types.append('building_power')  # Повышение лорда связано с зданиями

        if not action_types:
            action_types = ['building_power']  # По умолчанию

        # Получаем максимальный бонус для любого из типов действий
        max_bonus = 0
        for action_type in action_types:
            bonus = self.prime_time_manager.get_priority_bonus_for_action(action_type)
            max_bonus = max(max_bonus, bonus)

        return max_bonus

    def _calculate_waiting_bonus(self, emulator_data: Dict[str, Any]) -> int:
        """Расчет бонуса за время ожидания (+1 за час)"""
        last_processed = emulator_data.get('last_processed')
        if not last_processed:
            return 0

        try:
            last_time = datetime.fromisoformat(last_processed)
            hours_waiting = (datetime.now() - last_time).total_seconds() / 3600
            bonus = int(hours_waiting * self.priority_weights['per_hour_waiting'])
            return max(0, bonus)
        except (ValueError, TypeError):
            return 0

    def _should_wait_for_prime_time(self, recommended_actions: List[str]) -> Optional[Tuple[bool, Optional[datetime]]]:
        """
        Определение стоит ли ждать прайм-тайм

        Args:
            recommended_actions: Список рекомендуемых действий

        Returns:
            Кортеж (стоит_ждать, время_прайм_тайма) или None
        """
        if not recommended_actions:
            return None

        # Определяем типы действий для прайм-тайма
        action_types = []
        for action in recommended_actions:
            if 'building' in action:
                action_types.append('building_power')
            elif 'research' in action or 'evolution' in action:
                action_types.append('evolution_bonus')
            elif 'training' in action or 'soldier' in action:
                action_types.append('training_bonus')

        if not action_types:
            return None

        # Проверяем стоит ли ждать прайм-тайм
        should_wait, next_time = self.prime_time_manager.should_wait_for_prime_time(
            action_types,
            self.prime_time_settings['max_wait_hours']
        )

        return should_wait, next_time

    def _is_emulator_ready_for_processing(self, emulator_data: Dict[str, Any], current_time: datetime) -> bool:
        """
        Проверка готовности эмулятора к обработке

        Args:
            emulator_data: Данные эмулятора
            current_time: Текущее время

        Returns:
            True если готов к обработке
        """
        # Проверяем время следующей проверки
        next_check_time = emulator_data.get('next_check_time')
        if next_check_time:
            try:
                next_time = datetime.fromisoformat(next_check_time)
                if current_time < next_time:
                    return False
            except (ValueError, TypeError):
                pass

        # Проверяем ожидание прайм-тайма
        if emulator_data.get('waiting_for_prime_time', False):
            next_prime_time = emulator_data.get('next_prime_time_window')
            if next_prime_time:
                try:
                    prime_time = datetime.fromisoformat(next_prime_time)
                    if current_time < prime_time:
                        return False
                except (ValueError, TypeError):
                    pass

        return True

    def update_emulator_schedule(self, emulator_id: int, priority: EmulatorPriority) -> bool:
        """
        Обновление расписания эмулятора в БД

        Args:
            emulator_id: ID эмулятора
            priority: Объект приоритета с расчетами

        Returns:
            True если обновление успешно
        """
        try:
            # Обновляем данные в БД
            update_data = {
                'priority_score': priority.total_priority,
                'next_check_time': priority.next_check_time.isoformat() if priority.next_check_time else None,
                'waiting_for_prime_time': priority.waiting_for_prime_time,
                'next_prime_time_window': priority.next_prime_time_window.isoformat() if priority.next_prime_time_window else None,
            }

            success = self.database.update_emulator_progress(priority.emulator_index, **update_data)

            if success:
                logger.debug(f"📝 Обновлено расписание эмулятора {priority.emulator_index}")
            else:
                logger.warning(f"⚠️ Не удалось обновить расписание эмулятора {priority.emulator_index}")

            return success

        except Exception as e:
            logger.error(f"❌ Ошибка обновления расписания эмулятора {emulator_id}: {e}")
            return False

    def get_schedule_summary(self) -> Dict[str, Any]:
        """
        Получение сводки по расписанию и статусу планирования

        Returns:
            Словарь с детальной статистикой планирования
        """
        enabled_emulators = self.database.get_all_emulators(enabled_only=True)
        current_time = datetime.now()

        summary = {
            'total_enabled': len(enabled_emulators),
            'ready_now': 0,
            'waiting_for_time': 0,
            'waiting_for_prime_time': 0,
            'highest_priority': 0,
            'next_ready_time': None,
            'prime_time_status': self.prime_time_manager.get_status_summary()
        }

        next_ready_times = []

        for emulator_data in enabled_emulators:
            if self._is_emulator_ready_for_processing(emulator_data, current_time):
                summary['ready_now'] += 1
                priority = self.calculate_emulator_priority(emulator_data)
                summary['highest_priority'] = max(summary['highest_priority'], priority.total_priority)
            else:
                if emulator_data.get('waiting_for_prime_time', False):
                    summary['waiting_for_prime_time'] += 1
                else:
                    summary['waiting_for_time'] += 1

                # Собираем времена следующих проверок
                next_check = emulator_data.get('next_check_time')
                if next_check:
                    try:
                        next_time = datetime.fromisoformat(next_check)
                        next_ready_times.append(next_time)
                    except (ValueError, TypeError):
                        pass

        # Находим ближайшее время готовности
        if next_ready_times:
            summary['next_ready_time'] = min(next_ready_times).strftime('%Y-%m-%d %H:%M')

        return summary


# ========== ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР ПЛАНИРОВЩИКА ==========

_scheduler_instance = None


def get_scheduler(database: Database = None, prime_time_manager: PrimeTimeManager = None) -> SmartScheduler:
    """
    Получение глобального экземпляра планировщика (паттерн Singleton)

    Args:
        database: Экземпляр базы данных (создается автоматически если None)
        prime_time_manager: Менеджер прайм-таймов (создается автоматически если None)

    Returns:
        Настроенный экземпляр SmartScheduler
    """
    global _scheduler_instance

    if _scheduler_instance is None:
        if database is None:
            from utils.database import database as default_db
            database = default_db

        _scheduler_instance = SmartScheduler(database, prime_time_manager)
        logger.info("🎯 Создан глобальный экземпляр SmartScheduler")

    return _scheduler_instance


# ========== ФУНКЦИИ ДЛЯ УДОБСТВА ==========

def calculate_priority_for_emulator(emulator_index: int) -> Optional[EmulatorPriority]:
    """
    Быстрый расчет приоритета для конкретного эмулятора

    Args:
        emulator_index: Индекс эмулятора

    Returns:
        Объект EmulatorPriority или None если эмулятор не найден
    """
    try:
        scheduler = get_scheduler()

        # Получаем данные эмулятора
        emulator_data = scheduler.database.get_emulator_by_index(emulator_index)
        if not emulator_data:
            return None

        return scheduler.calculate_emulator_priority(emulator_data)

    except Exception as e:
        logger.error(f"❌ Ошибка расчета приоритета для эмулятора {emulator_index}: {e}")
        return None


def get_ready_emulators(max_concurrent: int = 5) -> List[EmulatorPriority]:
    """
    Быстрое получение готовых эмуляторов по приоритету

    Args:
        max_concurrent: Максимальное количество эмуляторов

    Returns:
        Список готовых эмуляторов по приоритету
    """
    try:
        scheduler = get_scheduler()
        return scheduler.get_ready_emulators_by_priority(max_concurrent)
    except Exception as e:
        logger.error(f"❌ Ошибка получения готовых эмуляторов: {e}")
        return []


if __name__ == "__main__":
    # Простой тест SmartScheduler
    import logging
    logging.basicConfig(level=logging.INFO)

    print("=== ТЕСТ SMARTSCHEDULER ===")
    print("Для полного тестирования запустите: python test_smart_scheduler.py")

    try:
        # Создаем планировщик
        scheduler = get_scheduler()
        print(f"✅ SmartScheduler создан: {scheduler}")

        # Получаем сводку
        summary = scheduler.get_schedule_summary()
        print(f"📊 Включенных эмуляторов: {summary['total_enabled']}")
        print(f"✅ Готовы сейчас: {summary['ready_now']}")

        print("\n🎯 ПРОМПТ 18 ЗАВЕРШЕН УСПЕШНО!")
        print("🚀 ГОТОВ К ПРОМПТУ 19: Кардинальная переработка orchestrator.py")

    except Exception as e:
        print(f"❌ Ошибка тестирования: {e}")
        print("💡 Убедитесь что созданы необходимые модули: utils/database.py, utils/prime_time_manager.py")