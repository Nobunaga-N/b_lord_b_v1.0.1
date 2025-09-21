"""
BuildingManager - "МОЗГИ" системы строительства и исследований Beast Lord Bot.
Обеспечивает ПАРАЛЛЕЛЬНУЮ работу зданий И исследований с учетом прайм-таймов.

КРИТИЧНО: Здания И исследования качаются ОДНОВРЕМЕННО в рамках доступных слотов!
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

from loguru import logger
from utils.database import Database
from utils.prime_time_manager import PrimeTimeManager


class ActionType(Enum):
    """Типы действий для планирования"""
    BUILDING = "building"
    RESEARCH = "research"
    LORD_UPGRADE = "lord_upgrade"
    NONE = "none"


@dataclass
class PlanedAction:
    """Запланированное действие (здание или исследование)"""
    action_type: ActionType
    item_name: str
    current_level: int
    target_level: int
    priority: int
    use_speedup: bool = False
    prime_time_bonus: int = 0
    estimated_duration: Optional[int] = None  # в минутах
    reason: str = ""


@dataclass
class SlotStatus:
    """Статус слотов строительства и исследований"""
    building_slots_total: int
    building_slots_free: int
    building_slots_active: int
    research_slots_total: int = 1  # Всегда 1 слот исследований
    research_slots_free: int = 1
    research_slots_active: int = 0
    active_buildings: List[Dict] = field(default_factory=list)
    active_research: List[Dict] = field(default_factory=list)


class BuildingManager:
    """
    МОЗГИ системы строительства и исследований.

    Ответственность:
    - Определение следующего действия (здание ИЛИ исследование)
    - Управление слотами строительства и исследований
    - Приоритизация действий с учетом прайм-таймов
    - Проверка готовности к повышению лорда
    - Интеграция с системой ускорений
    """

    def __init__(self, database: Database, prime_time_manager: Optional[PrimeTimeManager] = None):
        """
        Инициализация менеджера строительства

        Args:
            database: Экземпляр базы данных
            prime_time_manager: Менеджер прайм-таймов
        """
        self.database = database
        self.prime_time_manager = prime_time_manager or PrimeTimeManager()

        # Слоты строителей по уровню лорда (из ТЗ)
        self.builder_slots_by_lord = {
            # Лорд 10-15: 3 строителя
            10: 3, 11: 3, 12: 3, 13: 3, 14: 3, 15: 3,
            # Лорд 16+: 4 строителя
            16: 4, 17: 4, 18: 4, 19: 4, 20: 4
        }

        # Настройки приоритетов из ТЗ
        self.priority_settings = {
            'lord_upgrade_ready': 1000,    # Готовность к повышению лорда
            'blocking_building': 800,      # Здания, блокирующие лорда
            'free_slot_available': 500,    # Свободный слот доступен
            'completed_action': 300,       # Завершенное действие
            'prime_time_bonus': 200,       # Бонус за прайм-тайм
            'research_bonus': 100,         # Бонус за исследования (не блокируют)
        }

    def determine_next_action(self, emulator_data: Dict) -> Optional[PlanedAction]:
        """
        КЛЮЧЕВОЙ метод: определяет следующее действие (здание ИЛИ исследование)

        Args:
            emulator_data: Данные эмулятора (должны содержать id, lord_level)

        Returns:
            PlanedAction или None если нет доступных действий
        """
        emulator_id = emulator_data.get('id')
        lord_level = emulator_data.get('lord_level', 10)

        if not emulator_id:
            logger.error("ID эмулятора не указан")
            return None

        # 1. Проверяем готовность к повышению лорда (высший приоритет)
        if self.database.check_ready_for_lord_upgrade(emulator_id, lord_level):
            return PlanedAction(
                action_type=ActionType.LORD_UPGRADE,
                item_name="lord",
                current_level=lord_level,
                target_level=lord_level + 1,
                priority=self.priority_settings['lord_upgrade_ready'],
                reason="Готов к повышению лорда"
            )

        # 2. Получаем статус слотов
        slot_status = self.get_slot_status(emulator_id, lord_level)

        # 3. Получаем очередь приоритетных действий
        action_queue = self.get_action_priority_queue(emulator_id, lord_level)

        # 4. Выбираем лучшее доступное действие
        for action in action_queue:
            # Проверяем доступность слотов для действия
            if action.action_type == ActionType.BUILDING:
                if slot_status.building_slots_free > 0:
                    action.reason = f"Свободных слотов строительства: {slot_status.building_slots_free}"
                    return action
            elif action.action_type == ActionType.RESEARCH:
                if slot_status.research_slots_free > 0:
                    action.reason = f"Свободен слот исследований"
                    return action

        # Нет доступных действий
        return None

    def has_free_building_slot(self, emulator_id: int, lord_level: int) -> bool:
        """
        Проверка наличия свободного слота строительства

        Args:
            emulator_id: ID эмулятора
            lord_level: Уровень лорда (влияет на количество строителей)

        Returns:
            True если есть свободный слот
        """
        slot_status = self.get_slot_status(emulator_id, lord_level)
        return slot_status.building_slots_free > 0

    def has_free_research_slot(self, emulator_id: int) -> bool:
        """
        Проверка наличия свободного слота исследований

        Args:
            emulator_id: ID эмулятора

        Returns:
            True если слот исследований свободен
        """
        active_research = self.database.get_active_research(emulator_id)
        return len(active_research) == 0  # Только 1 слот исследований

    def get_slot_status(self, emulator_id: int, lord_level: int) -> SlotStatus:
        """
        Получение полного статуса слотов строительства и исследований

        Args:
            emulator_id: ID эмулятора
            lord_level: Уровень лорда

        Returns:
            SlotStatus с детальной информацией о слотах
        """
        # Определяем количество строителей по уровню лорда
        total_builders = self.builder_slots_by_lord.get(lord_level, 3)

        # Получаем активные строительства и исследования
        active_buildings = self.database.get_active_buildings(emulator_id)
        active_research = self.database.get_active_research(emulator_id)

        # Подсчитываем свободные слоты
        active_building_count = len(active_buildings)
        free_building_slots = max(0, total_builders - active_building_count)

        active_research_count = len(active_research)
        free_research_slots = max(0, 1 - active_research_count)  # Всегда 1 слот исследований

        return SlotStatus(
            building_slots_total=total_builders,
            building_slots_free=free_building_slots,
            building_slots_active=active_building_count,
            research_slots_total=1,
            research_slots_free=free_research_slots,
            research_slots_active=active_research_count,
            active_buildings=active_buildings,
            active_research=active_research
        )

    def get_action_priority_queue(self, emulator_id: int, lord_level: int) -> List[PlanedAction]:
        """
        Создание приоритетной очереди действий (здания + исследования)

        Args:
            emulator_id: ID эмулятора
            lord_level: Уровень лорда

        Returns:
            Отсортированный список PlanedAction по убыванию приоритета
        """
        actions = []

        # 1. Добавляем доступные здания
        building_actions = self._get_available_building_actions(emulator_id, lord_level)
        actions.extend(building_actions)

        # 2. Добавляем доступные исследования (ПАРАЛЛЕЛЬНО с зданиями)
        research_actions = self._get_available_research_actions(emulator_id, lord_level)
        actions.extend(research_actions)

        # 3. Применяем бонусы прайм-тайма
        self._apply_prime_time_bonuses(actions)

        # 4. Сортируем по приоритету (убывание)
        actions.sort(key=lambda x: x.priority, reverse=True)

        return actions

    def _get_available_building_actions(self, emulator_id: int, lord_level: int) -> List[PlanedAction]:
        """Получение доступных действий по строительству"""
        available_buildings = self.database.get_buildings_ready_for_upgrade(emulator_id)
        actions = []

        for building in available_buildings:
            building_name = building['building_name']
            current_level = building['current_level']
            target_level = building['target_level']

            # Базовый приоритет
            priority = self.priority_settings['free_slot_available']

            # Повышенный приоритет для зданий, блокирующих лорда
            if self._is_building_blocking_lord(emulator_id, lord_level + 1, building_name):
                priority += self.priority_settings['blocking_building']

            # Проверяем настройку ускорения из БД
            use_speedup = building.get('use_speedups', False)

            action = PlanedAction(
                action_type=ActionType.BUILDING,
                item_name=building_name,
                current_level=current_level,
                target_level=current_level + 1,  # Повышаем на 1 уровень
                priority=priority,
                use_speedup=use_speedup,
                reason=f"Здание {building_name} {current_level}->{current_level + 1}"
            )

            actions.append(action)

        return actions

    def _get_available_research_actions(self, emulator_id: int, lord_level: int) -> List[PlanedAction]:
        """Получение доступных действий по исследованиям"""
        available_research = self.database.get_available_research_for_upgrade(emulator_id)
        actions = []

        for research in available_research:
            research_name = research['research_name']
            current_level = research['current_level']
            target_level = research['target_level']

            # Базовый приоритет (исследования не блокируют лорда)
            priority = self.priority_settings['research_bonus']

            # Проверяем настройку ускорения из БД
            use_speedup = research.get('use_speedups', False)

            action = PlanedAction(
                action_type=ActionType.RESEARCH,
                item_name=research_name,
                current_level=current_level,
                target_level=current_level + 1,  # Повышаем на 1 уровень
                priority=priority,
                use_speedup=use_speedup,
                reason=f"Исследование {research_name} {current_level}->{current_level + 1}"
            )

            actions.append(action)

        return actions

    def _apply_prime_time_bonuses(self, actions: List[PlanedAction]) -> None:
        """Применение бонусов прайм-тайма к действиям"""
        # Получаем текущие активные прайм-таймы
        current_prime_actions = self.prime_time_manager.get_current_prime_actions()

        # Мапинг типов действий на прайм-тайм типы
        action_mapping = {
            ActionType.BUILDING: ['building_power', 'general_bonus'],
            ActionType.RESEARCH: ['general_bonus'],
        }

        for action in actions:
            if action.action_type in action_mapping:
                # Проверяем каждый подходящий прайм-тайм тип
                for prime_type in action_mapping[action.action_type]:
                    bonus = self.prime_time_manager.get_priority_bonus_for_action(prime_type)
                    if bonus > 0:
                        action.priority += bonus
                        action.prime_time_bonus += bonus
                        if not action.reason.endswith(")"):
                            action.reason += f" (прайм-тайм: +{bonus})"

    def _is_building_blocking_lord(self, emulator_id: int, target_lord_level: int, building_name: str) -> bool:
        """Проверка блокирует ли здание повышение лорда"""
        requirements = self.database.get_lord_requirements(target_lord_level)
        buildings_required = requirements.get('buildings', {})
        return building_name in buildings_required

    def update_building_progress(self, emulator_id: int, building_name: str,
                                completion_time: datetime) -> bool:
        """
        Обновление прогресса строительства в БД

        Args:
            emulator_id: ID эмулятора
            building_name: Название здания
            completion_time: Время завершения строительства

        Returns:
            True если обновление успешно
        """
        try:
            return self.database.start_building(
                emulator_id=emulator_id,
                building_name=building_name,
                completion_time=completion_time
            )
        except Exception as e:
            logger.error(f"Ошибка обновления прогресса строительства {building_name}: {e}")
            return False

    def update_research_progress(self, emulator_id: int, research_name: str,
                                completion_time: datetime) -> bool:
        """
        Обновление прогресса исследований в БД

        Args:
            emulator_id: ID эмулятора
            research_name: Название исследования
            completion_time: Время завершения исследования

        Returns:
            True если обновление успешно
        """
        try:
            return self.database.start_research(
                emulator_id=emulator_id,
                research_name=research_name,
                completion_time=completion_time
            )
        except Exception as e:
            logger.error(f"Ошибка обновления прогресса исследования {research_name}: {e}")
            return False

    def check_lord_upgrade_requirements(self, emulator_id: int, current_lord_level: int) -> Tuple[bool, Dict]:
        """
        Проверка готовности к повышению лорда

        Args:
            emulator_id: ID эмулятора
            current_lord_level: Текущий уровень лорда

        Returns:
            Кортеж (готов, {детали недостающих требований})
        """
        target_level = current_lord_level + 1
        ready, missing = self.database.check_lord_upgrade_readiness(emulator_id, target_level)

        return ready, missing

    def get_building_summary(self, emulator_id: int, lord_level: int) -> Dict[str, Any]:
        """
        Получение сводки по строительству и исследованиям

        Args:
            emulator_id: ID эмулятора
            lord_level: Уровень лорда

        Returns:
            Детальная сводка состояния
        """
        slot_status = self.get_slot_status(emulator_id, lord_level)
        next_action = self.determine_next_action({'id': emulator_id, 'lord_level': lord_level})
        lord_ready, missing_requirements = self.check_lord_upgrade_requirements(emulator_id, lord_level)

        summary = {
            'emulator_id': emulator_id,
            'lord_level': lord_level,
            'lord_upgrade_ready': lord_ready,
            'missing_requirements': missing_requirements,
            'slots': {
                'building': {
                    'total': slot_status.building_slots_total,
                    'active': slot_status.building_slots_active,
                    'free': slot_status.building_slots_free
                },
                'research': {
                    'total': slot_status.research_slots_total,
                    'active': slot_status.research_slots_active,
                    'free': slot_status.research_slots_free
                }
            },
            'active_buildings': slot_status.active_buildings,
            'active_research': slot_status.active_research,
            'next_action': None,
            'prime_time_status': self.prime_time_manager.get_status_summary()
        }

        if next_action:
            summary['next_action'] = {
                'type': next_action.action_type.value,
                'item': next_action.item_name,
                'level': f"{next_action.current_level}->{next_action.target_level}",
                'priority': next_action.priority,
                'use_speedup': next_action.use_speedup,
                'prime_time_bonus': next_action.prime_time_bonus,
                'reason': next_action.reason
            }

        return summary


# Глобальный экземпляр менеджера строительства
_building_manager_instance = None


def get_building_manager(database: Database = None, prime_time_manager: PrimeTimeManager = None) -> BuildingManager:
    """Получение глобального экземпляра менеджера строительства"""
    global _building_manager_instance

    if _building_manager_instance is None:
        if database is None:
            from utils.database import database as default_db
            database = default_db

        _building_manager_instance = BuildingManager(database, prime_time_manager)

    return _building_manager_instance