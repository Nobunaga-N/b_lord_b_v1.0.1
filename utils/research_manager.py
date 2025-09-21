"""
Менеджер исследований с ПАРАЛЛЕЛЬНОЙ логикой
Аналогичная система building_manager.py но для исследований

КРИТИЧНО:
- Исследования НЕ блокируют лорда
- Качаются ПАРАЛЛЕЛЬНО с зданиями в отдельной очереди
- Логика по веткам с ограничениями min_lord_level
- Интеграция с прайм-таймами для исследований
"""

from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import logging

# Подключение к общим модулям
from .database import Database
from .prime_time_manager import PrimeTimeManager

logger = logging.getLogger(__name__)


class ResearchBranch(Enum):
    """Ветки исследований"""
    TERRITORY_DEVELOPMENT = "territory_development"
    BASIC_COMBAT = "basic_combat"
    MEDIUM_COMBAT = "medium_combat"
    MARCH_SQUADS = "march_squads"
    ADVANCED_COMBAT = "advanced_combat"


@dataclass
class ResearchCandidate:
    """Кандидат на исследование"""
    research_name: str
    branch: ResearchBranch
    current_level: int
    target_level: int
    max_level: int
    min_lord_level: int
    priority: float
    use_speedup: bool
    prime_time_bonus: float = 0.0
    reason: str = ""


@dataclass
class ResearchSlotStatus:
    """Статус слотов исследований"""
    research_slots_total: int = 1  # Обычно 1 слот исследований
    research_slots_active: int = 0
    research_slots_free: int = 1
    active_research: List[Dict[str, Any]] = None


class ResearchManager:
    """
    Менеджер исследований - МОЗГИ системы исследований

    ПАРАЛЛЕЛЬНАЯ логика аналогично BuildingManager но для исследований:
    - Планирование исследований по веткам с min_lord_level
    - Отдельная очередь исследований (1 слот обычно)
    - НЕ блокируют лорда, качаются параллельно с зданиями
    """

    def __init__(self, database: Database, prime_time_manager: Optional[PrimeTimeManager] = None):
        self.database = database
        self.prime_time_manager = prime_time_manager

        # Настройки приоритетов для исследований
        self.priority_settings = {
            'territory_development': 100,  # Развитие территории (базовая ветка)
            'basic_combat': 80,  # Базовый бой
            'medium_combat': 70,  # Средний бой
            'march_squads': 60,  # Походные отряды
            'advanced_combat': 90,  # Продвинутый бой
            'prime_time_bonus': 25,  # Бонус прайм-тайма
            'free_research_slot': 50  # Базовый приоритет при свободном слоте
        }

        logger.info("ResearchManager инициализирован для ПАРАЛЛЕЛЬНЫХ исследований")

    def has_free_research_slot(self, emulator_id: int) -> bool:
        """
        Проверка есть ли свободный слот исследований

        Args:
            emulator_id: ID эмулятора

        Returns:
            True если есть свободный слот
        """
        slot_status = self.get_research_slot_status(emulator_id)
        return slot_status.research_slots_free > 0

    def get_research_slot_status(self, emulator_id: int) -> ResearchSlotStatus:
        """
        Получение статуса слотов исследований

        Args:
            emulator_id: ID эмулятора

        Returns:
            Статус слотов исследований
        """
        # Получаем активные исследования
        active_research = self.database.get_active_research(emulator_id)

        # Обычно 1 слот исследований (можно расширить)
        total_slots = 1
        active_count = len(active_research)
        free_slots = max(0, total_slots - active_count)

        return ResearchSlotStatus(
            research_slots_total=total_slots,
            research_slots_active=active_count,
            research_slots_free=free_slots,
            active_research=active_research
        )

    def get_available_research_candidates(self, emulator_id: int, lord_level: int) -> List[ResearchCandidate]:
        """
        Получение доступных кандидатов на исследование с учетом веток и ограничений

        Args:
            emulator_id: ID эмулятора
            lord_level: Уровень лорда

        Returns:
            Список кандидатов на исследование, отсортированный по приоритету
        """
        candidates = []

        # Получаем ветки исследований с ограничениями
        research_branches = self.database.get_research_branches_restrictions()

        # Получаем текущие уровни исследований эмулятора
        current_research_levels = self.database.get_research_levels(emulator_id)

        for branch_name, branch_data in research_branches.items():
            min_lord_level = branch_data.get('min_lord_level', 10)

            # Проверяем доступность ветки по уровню лорда
            if lord_level < min_lord_level:
                logger.debug(f"Ветка {branch_name} недоступна: лорд {lord_level} < {min_lord_level}")
                continue

            researches = branch_data.get('researches', {})

            for research_name, max_level in researches.items():
                current_level = current_research_levels.get(research_name, 0)

                # Можем качать дальше?
                if current_level < max_level:
                    # Проверяем не исследуется ли уже
                    is_already_researching = self._is_research_active(emulator_id, research_name)

                    if not is_already_researching:
                        candidate = self._create_research_candidate(
                            research_name=research_name,
                            branch_name=branch_name,
                            current_level=current_level,
                            max_level=max_level,
                            min_lord_level=min_lord_level,
                            emulator_id=emulator_id
                        )

                        if candidate:
                            candidates.append(candidate)

        # Применяем бонусы прайм-тайма
        self._apply_prime_time_bonuses(candidates)

        # Сортируем по приоритету (убывание)
        candidates.sort(key=lambda x: x.priority, reverse=True)

        logger.debug(f"Найдено {len(candidates)} кандидатов на исследование для лорда {lord_level}")
        return candidates

    def determine_next_research(self, emulator_id: int, lord_level: int) -> Optional[ResearchCandidate]:
        """
        Определение следующего исследования для выполнения

        Args:
            emulator_id: ID эмулятора
            lord_level: Уровень лорда

        Returns:
            Кандидат на исследование или None если нет доступных
        """
        # Проверяем есть ли свободный слот
        if not self.has_free_research_slot(emulator_id):
            logger.debug("Нет свободных слотов для исследований")
            return None

        # Получаем кандидатов
        candidates = self.get_available_research_candidates(emulator_id, lord_level)

        if not candidates:
            logger.debug("Нет доступных исследований")
            return None

        # Берем первого кандидата (высший приоритет)
        next_research = candidates[0]

        logger.info(f"Следующее исследование: {next_research.research_name} "
                    f"{next_research.current_level}->{next_research.target_level} "
                    f"(приоритет: {next_research.priority})")

        return next_research

    def _is_research_active(self, emulator_id: int, research_name: str) -> bool:
        """Проверка активно ли исследование"""
        active_research = self.database.get_active_research(emulator_id)
        return any(research.get('research_name') == research_name for research in active_research)

    def _create_research_candidate(self, research_name: str, branch_name: str,
                                   current_level: int, max_level: int, min_lord_level: int,
                                   emulator_id: int) -> Optional[ResearchCandidate]:
        """Создание кандидата на исследование"""

        try:
            # Определяем ветку
            branch = ResearchBranch(branch_name)
        except ValueError:
            logger.warning(f"Неизвестная ветка исследований: {branch_name}")
            branch = ResearchBranch.TERRITORY_DEVELOPMENT  # Fallback

        # Определяем приоритет на основе ветки
        base_priority = self.priority_settings.get(branch_name, self.priority_settings['free_research_slot'])

        # Получаем настройки ускорения
        use_speedup = self.database.get_speedup_setting(emulator_id, 'research', research_name, False)

        candidate = ResearchCandidate(
            research_name=research_name,
            branch=branch,
            current_level=current_level,
            target_level=current_level + 1,
            max_level=max_level,
            min_lord_level=min_lord_level,
            priority=base_priority,
            use_speedup=use_speedup,
            reason=f"Ветка {branch_name}, {current_level}->{current_level + 1}/{max_level}"
        )

        return candidate

    def _apply_prime_time_bonuses(self, candidates: List[ResearchCandidate]) -> None:
        """Применение бонусов прайм-тайма к кандидатам на исследование"""
        if not self.prime_time_manager:
            return

        # Получаем текущие активные прайм-таймы для исследований
        current_prime_actions = self.prime_time_manager.get_current_prime_actions()

        # Типы прайм-таймов связанные с исследованиями
        research_prime_types = ['research_power', 'general_bonus', 'evolution_bonus']

        for candidate in candidates:
            for prime_type in research_prime_types:
                if prime_type in current_prime_actions:
                    bonus = self.prime_time_manager.get_priority_bonus_for_action(prime_type)
                    if bonus > 0:
                        candidate.priority += bonus
                        candidate.prime_time_bonus += bonus
                        if not candidate.reason.endswith(")"):
                            candidate.reason += f" (прайм-тайм: +{bonus})"

    def update_research_progress(self, emulator_id: int, research_name: str,
                                 completion_time: datetime) -> bool:
        """
        Обновление прогресса исследования в БД

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

    def get_research_summary(self, emulator_id: int, lord_level: int) -> Dict[str, Any]:
        """
        Получение сводки по исследованиям

        Args:
            emulator_id: ID эмулятора
            lord_level: Уровень лорда

        Returns:
            Детальная сводка состояния исследований
        """
        slot_status = self.get_research_slot_status(emulator_id)
        next_research = self.determine_next_research(emulator_id, lord_level)
        candidates = self.get_available_research_candidates(emulator_id, lord_level)

        # Группируем кандидатов по веткам
        candidates_by_branch = {}
        for candidate in candidates[:10]:  # Показываем первые 10
            branch_name = candidate.branch.value
            if branch_name not in candidates_by_branch:
                candidates_by_branch[branch_name] = []
            candidates_by_branch[branch_name].append({
                'name': candidate.research_name,
                'level': f"{candidate.current_level}->{candidate.target_level}",
                'priority': candidate.priority,
                'use_speedup': candidate.use_speedup
            })

        summary = {
            'emulator_id': emulator_id,
            'lord_level': lord_level,
            'slots': {
                'total': slot_status.research_slots_total,
                'active': slot_status.research_slots_active,
                'free': slot_status.research_slots_free
            },
            'active_research': slot_status.active_research,
            'next_research': None,
            'available_candidates': len(candidates),
            'candidates_by_branch': candidates_by_branch,
            'prime_time_status': self.prime_time_manager.get_status_summary() if self.prime_time_manager else None
        }

        if next_research:
            summary['next_research'] = {
                'name': next_research.research_name,
                'branch': next_research.branch.value,
                'level': f"{next_research.current_level}->{next_research.target_level}",
                'priority': next_research.priority,
                'use_speedup': next_research.use_speedup,
                'prime_time_bonus': next_research.prime_time_bonus,
                'reason': next_research.reason
            }

        return summary

    def should_wait_for_research_prime_time(self, candidates: List[ResearchCandidate],
                                            max_wait_hours: float = 2.0) -> Tuple[bool, Optional[datetime]]:
        """
        Проверка стоит ли ждать прайм-тайм для исследований

        Args:
            candidates: Кандидаты на исследование
            max_wait_hours: Максимальное время ожидания в часах

        Returns:
            Кортеж (стоит_ждать, время_следующего_прайм_тайма)
        """
        if not self.prime_time_manager or not candidates:
            return False, None

        # Проверяем прайм-таймы для исследований
        research_action_types = ['research_power', 'general_bonus', 'evolution_bonus']

        return self.prime_time_manager.should_wait_for_prime_time(
            action_types=research_action_types,
            max_wait_hours=max_wait_hours
        )


# ========== ФУНКЦИЯ ДЛЯ УДОБСТВА ==========

def get_research_manager(database: Optional[Database] = None,
                         prime_time_manager: Optional[PrimeTimeManager] = None) -> ResearchManager:
    """
    Фабричная функция для создания ResearchManager

    Args:
        database: Экземпляр базы данных (если None, создаст новый)
        prime_time_manager: Менеджер прайм-таймов (опционально)

    Returns:
        Настроенный экземпляр ResearchManager
    """
    if database is None:
        database = Database("data/game_bot.db")

    if prime_time_manager is None:
        try:
            prime_time_manager = PrimeTimeManager()
        except Exception as e:
            logger.warning(f"Не удалось инициализировать PrimeTimeManager: {e}")
            prime_time_manager = None

    return ResearchManager(database, prime_time_manager)


if __name__ == "__main__":
    # Простой тест ResearchManager
    logging.basicConfig(level=logging.INFO)

    try:
        research_manager = get_research_manager()

        # Тестируем для эмулятора ID=1, лорд уровень 15
        test_emulator_id = 1
        test_lord_level = 15

        print("=== ТЕСТ RESEARCH MANAGER ===")

        # 1. Проверяем слоты
        slot_status = research_manager.get_research_slot_status(test_emulator_id)
        print(f"Слоты исследований: {slot_status.research_slots_free}/{slot_status.research_slots_total}")

        # 2. Получаем кандидатов
        candidates = research_manager.get_available_research_candidates(test_emulator_id, test_lord_level)
        print(f"Найдено кандидатов: {len(candidates)}")

        for candidate in candidates[:5]:
            print(f"  - {candidate.research_name} ({candidate.branch.value}) "
                  f"{candidate.current_level}->{candidate.target_level} "
                  f"приоритет: {candidate.priority}")

        # 3. Определяем следующее исследование
        next_research = research_manager.determine_next_research(test_emulator_id, test_lord_level)
        if next_research:
            print(f"\nСледующее исследование: {next_research.research_name}")
        else:
            print("\nНет доступных исследований")

        # 4. Получаем сводку
        summary = research_manager.get_research_summary(test_emulator_id, test_lord_level)
        print(f"\nСводка: {summary['available_candidates']} кандидатов, "
              f"{summary['slots']['free']} свободных слотов")

        print("\n✅ Тест ResearchManager завершен успешно!")

    except Exception as e:
        print(f"❌ Ошибка тестирования: {e}")