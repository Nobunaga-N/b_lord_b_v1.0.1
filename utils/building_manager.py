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


@dataclass
class ResourceRequirement:
    """Требования ресурсов для действия"""
    food: int = 0
    wood: int = 0
    stone: int = 0
    iron: int = 0
    gold: int = 0


@dataclass
class ResourceValidationResult:
    """Результат валидации ресурсов"""
    has_enough: bool
    missing_resources: Dict[str, int]
    wait_time_estimate: Optional[int] = None  # в минутах


@dataclass
class ParallelActionQueue:
    """Очередь параллельных действий с приоритетами"""
    building_actions: List[PlanedAction]
    research_actions: List[PlanedAction]
    blocked_actions: List[PlanedAction]  # Заблокированы нехваткой ресурсов
    total_priority_score: int


class BuildingManager:
    """
    МОЗГИ системы строительства и исследований.

    Обеспечивает ПАРАЛЛЕЛЬНУЮ работу зданий И исследований с учетом:
    - Свободных слотов строительства (3-4 в зависимости от уровня лорда)
    - Свободных слотов исследований (1 слот)
    - Приоритетов действий и прайм-таймов
    - Валидации ресурсов и стратегий при нехватке
    """

    def __init__(self, database: Database, prime_time_manager: PrimeTimeManager = None):
        """
        Инициализация менеджера строительства

        Args:
            database: Экземпляр базы данных
            prime_time_manager: Менеджер прайм-таймов (опционально)
        """
        self.database = database
        self.prime_time_manager = prime_time_manager

        # Настройки слотов строителей по уровню лорда
        self.builder_slots_by_lord = {
            10: 3, 11: 3, 12: 3, 13: 3, 14: 3, 15: 3,  # 3 строителя для лордов 10-15
            16: 4, 17: 4, 18: 4, 19: 4, 20: 4  # 4 строителя для лордов 16+
        }

        # Настройки приоритетов из конфига
        self.priority_settings = {
            'lord_upgrade_ready': 1000,      # Готов к повышению лорда
            'completed_buildings': 500,      # Завершенные постройки
            'completed_research': 500,       # Завершенные исследования
            'free_building_slot': 200,       # Свободный слот строительства
            'free_research_slot': 200,       # Свободный слот исследований
            'prime_time_bonus': 100,         # Бонус за прайм-тайм
            'per_hour_waiting': 1            # За каждый час ожидания
        }

        logger.debug("BuildingManager инициализирован")

    def determine_next_action(self, emulator: Dict) -> Optional[PlanedAction]:
        """
        ОПРЕДЕЛЯЕТ следующее действие (здание ИЛИ исследование)

        Args:
            emulator: Данные эмулятора

        Returns:
            Следующее запланированное действие или None
        """
        emulator_id = emulator['id']
        lord_level = emulator.get('lord_level', 10)

        logger.debug(f"Определение следующего действия для эмулятора {emulator_id}, лорд {lord_level}")

        # Получаем статус слотов
        slot_status = self.get_slot_status(emulator_id, lord_level)

        # Если нет свободных слотов ни для зданий, ни для исследований
        if slot_status.building_slots_free == 0 and slot_status.research_slots_free == 0:
            logger.debug("Нет свободных слотов для строительства или исследований")
            return None

        # Получаем приоритетную очередь действий
        action_queue = self.get_action_priority_queue(emulator_id, lord_level)

        if not action_queue:
            logger.debug("Нет доступных действий в очереди")
            return None

        # Фильтруем действия по доступным слотам
        filtered_actions = []
        for action in action_queue:
            if action.action_type == ActionType.BUILDING and slot_status.building_slots_free > 0:
                filtered_actions.append(action)
            elif action.action_type == ActionType.RESEARCH and slot_status.research_slots_free > 0:
                filtered_actions.append(action)

        if not filtered_actions:
            logger.debug("Нет действий, подходящих под свободные слоты")
            return None

        # Возвращаем действие с наивысшим приоритетом
        next_action = filtered_actions[0]
        logger.info(f"Выбрано действие: {next_action.action_type.value} {next_action.item_name} "
                   f"{next_action.current_level}->{next_action.target_level} (приоритет: {next_action.priority})")

        return next_action

    def get_slot_status(self, emulator_id: int, lord_level: int) -> SlotStatus:
        """
        Получение статуса слотов строительства и исследований

        Args:
            emulator_id: ID эмулятора
            lord_level: Уровень лорда

        Returns:
            Статус всех слотов
        """
        # Определяем общее количество слотов строителей
        building_slots_total = self.builder_slots_by_lord.get(lord_level, 3)

        # Получаем активные строительства и исследования
        active_buildings = self.database.get_active_buildings(emulator_id)
        active_research = self.database.get_active_research(emulator_id)

        building_slots_active = len(active_buildings)
        research_slots_active = len(active_research)

        # Рассчитываем свободные слоты
        building_slots_free = max(0, building_slots_total - building_slots_active)
        research_slots_free = max(0, 1 - research_slots_active)  # Всегда 1 слот исследований

        status = SlotStatus(
            building_slots_total=building_slots_total,
            building_slots_free=building_slots_free,
            building_slots_active=building_slots_active,
            research_slots_total=1,
            research_slots_free=research_slots_free,
            research_slots_active=research_slots_active,
            active_buildings=active_buildings,
            active_research=active_research
        )

        logger.debug(f"Статус слотов для эмулятора {emulator_id}: "
                    f"строительство {building_slots_free}/{building_slots_total}, "
                    f"исследования {research_slots_free}/1")

        return status

    def has_free_building_slot(self, emulator_id: int, lord_level: int) -> bool:
        """Проверка наличия свободного слота строительства"""
        slot_status = self.get_slot_status(emulator_id, lord_level)
        return slot_status.building_slots_free > 0

    def has_free_research_slot(self, emulator_id: int) -> bool:
        """Проверка наличия свободного слота исследований"""
        active_research = self.database.get_active_research(emulator_id)
        return len(active_research) == 0  # Только 1 слот исследований

    def get_action_priority_queue(self, emulator_id: int, lord_level: int) -> List[PlanedAction]:
        """
        ПЛАНИРУЕТ очередь действий (здания + исследования по готовности)

        Args:
            emulator_id: ID эмулятора
            lord_level: Уровень лорда

        Returns:
            Отсортированный список действий по приоритету
        """
        logger.debug(f"Формирование очереди действий для эмулятора {emulator_id}")

        actions = []

        # Получаем кандидатов на строительство
        building_candidates = self._get_building_candidates(emulator_id, lord_level)
        actions.extend(building_candidates)

        # Получаем кандидатов на исследования
        research_candidates = self._get_research_candidates(emulator_id, lord_level)
        actions.extend(research_candidates)

        # Применяем бонусы прайм-тайма
        if self.prime_time_manager:
            self._apply_prime_time_bonuses(actions)

        # Сортируем по приоритету (убывание)
        actions.sort(key=lambda x: x.priority, reverse=True)

        logger.debug(f"Сформирована очередь из {len(actions)} действий")
        return actions

    def _get_building_candidates(self, emulator_id: int, lord_level: int) -> List[PlanedAction]:
        """Получение кандидатов на строительство"""
        actions = []

        # Получаем текущие уровни зданий
        current_buildings = self.database.get_building_levels(emulator_id)

        # Получаем требования для следующего уровня лорда
        target_lord_level = lord_level + 1
        lord_requirements = self.database.get_lord_requirements(target_lord_level)

        if lord_requirements and 'buildings' in lord_requirements:
            required_buildings = lord_requirements['buildings']

            for building_name, required_level in required_buildings.items():
                current_level = current_buildings.get(building_name, 0)

                if current_level < required_level:
                    # Определяем приоритет
                    priority = self.priority_settings['lord_upgrade_ready']
                    if self._is_building_blocking_lord(emulator_id, target_lord_level, building_name):
                        priority += 200  # Дополнительный приоритет для блокирующих зданий

                    # Проверяем настройки ускорения
                    use_speedup = self.database.get_speedup_setting(emulator_id, 'buildings', building_name, False)

                    action = PlanedAction(
                        action_type=ActionType.BUILDING,
                        item_name=building_name,
                        current_level=current_level,
                        target_level=current_level + 1,  # Повышаем на 1 уровень
                        priority=priority,
                        use_speedup=use_speedup,
                        reason=f"Требование для лорда {target_lord_level}"
                    )

                    actions.append(action)

        return actions

    def _get_research_candidates(self, emulator_id: int, lord_level: int) -> List[PlanedAction]:
        """Получение кандидатов на исследования"""
        actions = []

        # Получаем текущие уровни исследований
        current_research = self.database.get_research_levels(emulator_id)

        # Получаем доступные исследования (упрощенно)
        available_research = ['Economy', 'Military', 'Defense']  # Базовые ветки

        for research_name in available_research:
            current_level = current_research.get(research_name, 0)

            # Можем качать до уровня лорда
            if current_level < lord_level:
                priority = self.priority_settings['free_research_slot']

                # Проверяем настройки ускорения
                use_speedup = self.database.get_speedup_setting(emulator_id, 'research', research_name, False)

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
            'prime_time_status': self.prime_time_manager.get_status_summary() if self.prime_time_manager else None
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

    # ========== НОВЫЕ МЕТОДЫ ИЗ ПРОМПТА 16 ==========

    def get_parallel_action_queue(self, emulator_id: int, lord_level: int) -> ParallelActionQueue:
        """
        ПАРАЛЛЕЛЬНОЕ планирование действий на основе свободных слотов

        Args:
            emulator_id: ID эмулятора
            lord_level: Уровень лорда

        Returns:
            Очередь параллельных действий с приоритетами
        """
        logger.debug(f"Планирование параллельных действий для эмулятора {emulator_id}")

        # Получаем статус слотов
        slot_status = self.get_slot_status(emulator_id, lord_level)

        # Получаем доступные действия
        available_actions = self.get_action_priority_queue(emulator_id, lord_level)

        # Получаем текущие ресурсы эмулятора
        current_resources = self._get_current_resources(emulator_id)

        building_queue = []
        research_queue = []
        blocked_queue = []

        # ПАРАЛЛЕЛЬНОЕ планирование зданий
        if slot_status.building_slots_free > 0:
            building_candidates = [a for a in available_actions if a.action_type == ActionType.BUILDING]
            building_queue = self._validate_and_plan_buildings(
                building_candidates,
                slot_status.building_slots_free,
                current_resources
            )

        # ПАРАЛЛЕЛЬНОЕ планирование исследований
        if slot_status.research_slots_free > 0:
            research_candidates = [a for a in available_actions if a.action_type == ActionType.RESEARCH]
            research_queue = self._validate_and_plan_research(
                research_candidates,
                slot_status.research_slots_free,
                current_resources
            )

        # Проверяем заблокированные действия
        all_planned = building_queue + research_queue
        for action in available_actions:
            if action not in all_planned:
                # Проверяем почему действие не запланировано
                if not self._has_enough_resources(action, current_resources):
                    blocked_queue.append(action)

        total_score = sum(a.priority for a in building_queue + research_queue)

        return ParallelActionQueue(
            building_actions=building_queue,
            research_actions=research_queue,
            blocked_actions=blocked_queue,
            total_priority_score=total_score
        )

    def _validate_and_plan_buildings(self, candidates: List[PlanedAction],
                                    available_slots: int,
                                    current_resources: Dict[str, int]) -> List[PlanedAction]:
        """
        Валидация и планирование зданий для свободных слотов

        Args:
            candidates: Кандидаты на строительство
            available_slots: Количество свободных слотов
            current_resources: Текущие ресурсы

        Returns:
            Список запланированных действий по строительству
        """
        planned_buildings = []
        resources_copy = current_resources.copy()

        # Сортируем по приоритету (высший приоритет первым)
        sorted_candidates = sorted(candidates, key=lambda x: x.priority, reverse=True)

        for action in sorted_candidates:
            if len(planned_buildings) >= available_slots:
                break

            # Проверяем ресурсы для этого здания
            if self._can_afford_action(action, resources_copy):
                planned_buildings.append(action)

                # Вычитаем ресурсы из копии (симуляция трат)
                requirements = self._get_resource_requirements(action)
                self._deduct_resources(resources_copy, requirements)

                logger.debug(f"Запланировано здание: {action.item_name} {action.current_level}->{action.target_level}")
            else:
                logger.debug(f"Недостаточно ресурсов для {action.item_name}")

        return planned_buildings

    def _validate_and_plan_research(self, candidates: List[PlanedAction],
                                   available_slots: int,
                                   current_resources: Dict[str, int]) -> List[PlanedAction]:
        """
        Валидация и планирование исследований для свободных слотов

        Args:
            candidates: Кандидаты на исследование
            available_slots: Количество свободных слотов (обычно 1)
            current_resources: Текущие ресурсы

        Returns:
            Список запланированных исследований
        """
        planned_research = []
        resources_copy = current_resources.copy()

        # Сортируем по приоритету (высший приоритет первым)
        sorted_candidates = sorted(candidates, key=lambda x: x.priority, reverse=True)

        for action in sorted_candidates:
            if len(planned_research) >= available_slots:
                break

            # Проверяем ресурсы для исследования
            if self._can_afford_action(action, resources_copy):
                planned_research.append(action)

                # Вычитаем ресурсы из копии
                requirements = self._get_resource_requirements(action)
                self._deduct_resources(resources_copy, requirements)

                logger.debug(f"Запланировано исследование: {action.item_name} уровень {action.target_level}")
            else:
                logger.debug(f"Недостаточно ресурсов для исследования {action.item_name}")

        return planned_research

    def validate_resources_for_action(self, emulator_id: int, action: PlanedAction) -> ResourceValidationResult:
        """
        Валидация ресурсов для конкретного действия

        Args:
            emulator_id: ID эмулятора
            action: Планируемое действие

        Returns:
            Результат валидации ресурсов
        """
        current_resources = self._get_current_resources(emulator_id)
        requirements = self._get_resource_requirements(action)

        missing = {}
        for resource_type in ['food', 'wood', 'stone', 'iron', 'gold']:
            required = getattr(requirements, resource_type, 0)
            available = current_resources.get(resource_type, 0)

            if required > available:
                missing[resource_type] = required - available

        has_enough = len(missing) == 0
        wait_time = None

        if not has_enough:
            # Оценка времени ожидания (упрощенная)
            wait_time = self._estimate_resource_wait_time(emulator_id, missing)

        return ResourceValidationResult(
            has_enough=has_enough,
            missing_resources=missing,
            wait_time_estimate=wait_time
        )

    def handle_resource_shortage(self, emulator_id: int, action: PlanedAction) -> Dict[str, Any]:
        """
        Обработка нехватки ресурсов для действия

        Args:
            emulator_id: ID эмулятора
            action: Действие с нехваткой ресурсов

        Returns:
            Стратегия решения проблемы с ресурсами
        """
        validation = self.validate_resources_for_action(emulator_id, action)

        if validation.has_enough:
            return {'status': 'sufficient', 'action': 'proceed'}

        strategies = []

        # Стратегия 1: Ожидание накопления ресурсов
        if validation.wait_time_estimate and validation.wait_time_estimate < 120:  # Меньше 2 часов
            strategies.append({
                'type': 'wait',
                'duration': validation.wait_time_estimate,
                'description': f"Ожидание накопления ресурсов ({validation.wait_time_estimate} мин)"
            })

        # Стратегия 2: Сбор ресурсов с карты
        collection_actions = self._suggest_resource_collection(emulator_id, validation.missing_resources)
        if collection_actions:
            strategies.append({
                'type': 'collect',
                'actions': collection_actions,
                'description': "Сбор недостающих ресурсов с карты"
            })

        # Стратегия 3: Атака диких существ для ресурсов
        if self._can_attack_for_resources(emulator_id, validation.missing_resources):
            strategies.append({
                'type': 'attack',
                'description': "Атака диких существ для получения ресурсов"
            })

        # Стратегия 4: Отложить действие
        strategies.append({
            'type': 'postpone',
            'description': "Отложить действие до накопления ресурсов"
        })

        return {
            'status': 'insufficient',
            'missing': validation.missing_resources,
            'strategies': strategies,
            'recommended_strategy': strategies[0] if strategies else None
        }

    def get_resource_optimization_plan(self, emulator_id: int, lord_level: int) -> Dict[str, Any]:
        """
        КРИТИЧНО: План оптимизации ресурсов для ВСЕХ зданий связанных с лордом

        Args:
            emulator_id: ID эмулятора
            lord_level: Уровень лорда

        Returns:
            План оптимизации ресурсов
        """
        logger.info(f"Создание плана оптимизации ресурсов для лорда {lord_level}")

        # Получаем требования для следующего уровня лорда
        target_lord_level = lord_level + 1
        lord_requirements = self.database.get_lord_requirements(target_lord_level)

        if not lord_requirements:
            return {'status': 'no_requirements', 'message': f'Нет требований для лорда {target_lord_level}'}

        # КРИТИЧНО: ВСЕ здания из списка связаны с лордом
        required_buildings = lord_requirements.get('buildings', {})
        current_buildings = self.database.get_building_levels(emulator_id)

        total_resource_need = ResourceRequirement()
        building_plan = []

        # Планируем ВСЕ необходимые здания для лорда
        for building_name, required_level in required_buildings.items():
            current_level = current_buildings.get(building_name, 0)

            if current_level < required_level:
                # Планируем поэтапное строительство
                for level in range(current_level + 1, required_level + 1):
                    action = PlanedAction(
                        action_type=ActionType.BUILDING,
                        item_name=building_name,
                        current_level=level - 1,
                        target_level=level,
                        priority=1000,  # Максимальный приоритет для зданий лорда
                        reason=f"Требование для лорда {target_lord_level}"
                    )

                    building_plan.append(action)

                    # Добавляем к общим потребностям в ресурсах
                    requirements = self._get_resource_requirements(action)
                    total_resource_need.food += requirements.food
                    total_resource_need.wood += requirements.wood
                    total_resource_need.stone += requirements.stone
                    total_resource_need.iron += requirements.iron
                    total_resource_need.gold += requirements.gold

        current_resources = self._get_current_resources(emulator_id)
        resource_gap = self._calculate_resource_gap(current_resources, total_resource_need)

        return {
            'status': 'success',
            'target_lord_level': target_lord_level,
            'building_plan': building_plan,
            'total_resource_need': total_resource_need,
            'current_resources': current_resources,
            'resource_gap': resource_gap,
            'estimated_completion_time': self._estimate_lord_upgrade_time(building_plan)
        }

    # ========== ПРИВАТНЫЕ ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ==========

    def _get_current_resources(self, emulator_id: int) -> Dict[str, int]:
        """Получение текущих ресурсов эмулятора"""
        # Заглушка - в реальности парсим из игры или берем из БД
        return {
            'food': 1000000,
            'wood': 1000000,
            'stone': 500000,
            'iron': 300000,
            'gold': 100000
        }

    def _get_resource_requirements(self, action: PlanedAction) -> ResourceRequirement:
        """Получение требований ресурсов для действия"""
        # Заглушка - в реальности берем из конфига или БД
        base_cost = 1000 * (action.target_level ** 2)

        if action.action_type == ActionType.BUILDING:
            return ResourceRequirement(
                food=base_cost,
                wood=base_cost // 2,
                stone=base_cost // 3,
                iron=base_cost // 4,
                gold=base_cost // 10
            )
        elif action.action_type == ActionType.RESEARCH:
            return ResourceRequirement(
                food=base_cost // 2,
                wood=base_cost // 4,
                gold=base_cost // 5
            )

        return ResourceRequirement()

    def _can_afford_action(self, action: PlanedAction, available_resources: Dict[str, int]) -> bool:
        """Проверка достаточности ресурсов для действия"""
        requirements = self._get_resource_requirements(action)

        return (
            available_resources.get('food', 0) >= requirements.food and
            available_resources.get('wood', 0) >= requirements.wood and
            available_resources.get('stone', 0) >= requirements.stone and
            available_resources.get('iron', 0) >= requirements.iron and
            available_resources.get('gold', 0) >= requirements.gold
        )

    def _has_enough_resources(self, action: PlanedAction, available_resources: Dict[str, int]) -> bool:
        """Alias для _can_afford_action для совместимости"""
        return self._can_afford_action(action, available_resources)

    def _deduct_resources(self, resources: Dict[str, int], requirements: ResourceRequirement) -> None:
        """Вычитание ресурсов из словаря (для симуляции трат)"""
        resources['food'] = max(0, resources.get('food', 0) - requirements.food)
        resources['wood'] = max(0, resources.get('wood', 0) - requirements.wood)
        resources['stone'] = max(0, resources.get('stone', 0) - requirements.stone)
        resources['iron'] = max(0, resources.get('iron', 0) - requirements.iron)
        resources['gold'] = max(0, resources.get('gold', 0) - requirements.gold)

    def _estimate_resource_wait_time(self, emulator_id: int, missing_resources: Dict[str, int]) -> int:
        """Оценка времени ожидания накопления ресурсов"""
        # Упрощенная оценка: 1 час на каждые 100К недостающих ресурсов
        total_missing = sum(missing_resources.values())
        return min(total_missing // 100000 * 60, 480)  # Максимум 8 часов

    def _suggest_resource_collection(self, emulator_id: int, missing_resources: Dict[str, int]) -> List[str]:
        """Предложение действий по сбору ресурсов"""
        suggestions = []

        for resource, amount in missing_resources.items():
            if amount > 50000:  # Стоит собирать только значительные объемы
                suggestions.append(f"collect_{resource}_tiles")

        return suggestions

    def _can_attack_for_resources(self, emulator_id: int, missing_resources: Dict[str, int]) -> bool:
        """Проверка возможности атаки для получения ресурсов"""
        # Упрощенная проверка - есть ли войска и энергия
        return True  # Заглушка

    def _calculate_resource_gap(self, current: Dict[str, int], needed: ResourceRequirement) -> Dict[str, int]:
        """Расчет разрыва в ресурсах"""
        return {
            'food': max(0, needed.food - current.get('food', 0)),
            'wood': max(0, needed.wood - current.get('wood', 0)),
            'stone': max(0, needed.stone - current.get('stone', 0)),
            'iron': max(0, needed.iron - current.get('iron', 0)),
            'gold': max(0, needed.gold - current.get('gold', 0))
        }

    def _estimate_lord_upgrade_time(self, building_plan: List[PlanedAction]) -> int:
        """Оценка времени до завершения всех зданий для лорда"""
        if not building_plan:
            return 0

        # Упрощенная оценка: сумма времени всех зданий с учетом параллельности
        total_time = sum(getattr(action, 'estimated_duration', 60) for action in building_plan)

        # Учитываем параллельное строительство (3-4 слота)
        parallel_factor = 3.5
        return int(total_time / parallel_factor)


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