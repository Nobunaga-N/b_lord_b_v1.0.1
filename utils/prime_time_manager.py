"""
Система управления прайм-таймами для Beast Lord The New Land.
Определяет оптимальные времена для различных игровых действий.
ИСПРАВЛЕНО: Учитывает периоды обновления заданий (X:00-X:05) когда прайм-тайм НЕ работает.
"""

import yaml
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path

from loguru import logger


class PrimeTimeAction:
    """Класс для представления действия в прайм-тайм"""

    def __init__(self, action_type: str, bonus_description: str = "",
                 day_of_week: int = 0, hour: int = 0, minute: int = 0):
        self.action_type = action_type
        self.bonus_description = bonus_description
        self.day_of_week = day_of_week  # 0=ПН, 6=ВС
        self.hour = hour
        self.minute = minute

    def to_dict(self) -> dict:
        """Конвертация в словарь"""
        return {
            'action_type': self.action_type,
            'bonus_description': self.bonus_description,
            'day_of_week': self.day_of_week,
            'hour': self.hour,
            'minute': self.minute
        }

    def __str__(self) -> str:
        days = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС']
        return f"{days[self.day_of_week]} {self.hour:02d}:{self.minute:02d} - {self.action_type}"


class PrimeTimeManager:
    """Класс для управления прайм-таймами"""

    def __init__(self, config_path: str = "configs/prime_times.yaml"):
        """
        Инициализация менеджера прайм-таймов

        Args:
            config_path: Путь к файлу конфигурации прайм-таймов
        """
        self.config_path = Path(config_path)
        self.prime_times: Dict[str, List[PrimeTimeAction]] = {}

        # Настройки из конфига
        self.settings = {
            'max_wait_hours': 2.0,
            'tolerance_minutes': 3,  # Уменьшено до 3 минут
            'maintenance_periods': {
                'duration_minutes': 5,  # X:00-X:05 - обновление заданий
                'starts_at_minute': 0
            }
        }

        # Загружаем прайм-таймы
        self.load_prime_times_from_config()

        logger.info(f"Инициализирован PrimeTimeManager, загружено {self._count_total_actions()} прайм-таймов")

    def is_maintenance_period(self, target_time: Optional[datetime] = None) -> bool:
        """
        Проверка является ли указанное время периодом обновления (X:00-X:05)

        Args:
            target_time: Время для проверки (по умолчанию - текущее)

        Returns:
            True если это период обновления, False иначе
        """
        if target_time is None:
            target_time = datetime.now()

        # Прайм-тайм НЕ работает в периоды X:00-X:05 каждый час
        maintenance_duration = self.settings['maintenance_periods']['duration_minutes']
        maintenance_start = self.settings['maintenance_periods']['starts_at_minute']

        current_minute = target_time.minute

        # Проверяем находимся ли в периоде обновления
        is_maintenance = maintenance_start <= current_minute < (maintenance_start + maintenance_duration)

        if is_maintenance:
            logger.debug(f"Период обновления заданий: {target_time.strftime('%H:%M')} - прайм-тайм не работает")

        return is_maintenance

    def load_prime_times_from_config(self) -> bool:
        """
        Загрузка прайм-таймов из YAML конфига

        Returns:
            True если загрузка успешна, False иначе
        """
        try:
            if not self.config_path.exists():
                logger.warning(f"Файл прайм-таймов не найден: {self.config_path}")
                self._load_default_prime_times()
                return False

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)

            if not config_data:
                logger.warning("Конфиг прайм-таймов пустой")
                self._load_default_prime_times()
                return False

            # Загружаем настройки если есть
            if 'settings' in config_data:
                self.settings.update(config_data['settings'])
                logger.debug(f"Загружены настройки: {self.settings}")

            if 'prime_times' not in config_data:
                logger.warning("Секция 'prime_times' не найдена в конфиге")
                self._load_default_prime_times()
                return False

            # Очищаем существующие данные
            self.prime_times = {}

            # Загружаем данные по дням недели
            for day_name, day_schedule in config_data['prime_times'].items():
                day_num = self._day_name_to_number(day_name)
                if day_num == -1:
                    logger.warning(f"Неизвестный день недели: {day_name}")
                    continue

                for time_str, actions in day_schedule.items():
                    try:
                        hour, minute = self._parse_time(time_str)

                        # Обрабатываем действия для этого времени
                        if isinstance(actions, str):
                            # Простая строка - одно действие
                            action_type, bonus = self._parse_action_string(actions)
                            action = PrimeTimeAction(action_type, bonus, day_num, hour, minute)
                            self._add_action(action)
                        elif isinstance(actions, list):
                            # Список действий
                            for action_str in actions:
                                action_type, bonus = self._parse_action_string(action_str)
                                action = PrimeTimeAction(action_type, bonus, day_num, hour, minute)
                                self._add_action(action)

                    except Exception as e:
                        logger.warning(f"Ошибка парсинга времени {time_str}: {e}")
                        continue

            logger.success(f"Загружено {self._count_total_actions()} прайм-таймов из конфига")
            return True

        except Exception as e:
            logger.error(f"Ошибка загрузки прайм-таймов: {e}")
            self._load_default_prime_times()
            return False

    def _load_default_prime_times(self) -> None:
        """Загрузка базовых прайм-таймов если конфиг недоступен"""
        logger.info("Загружаем базовые прайм-таймы...")

        # Базовые прайм-таймы на основе Prime Time_fixed_v4.txt (ПРАВИЛЬНЫЕ данные)
        default_actions = [
            # Понедельник - развитие муравейника (00:05-23:05)
            (0, 0, 5, "wild_bonus", "сила эволюции, ускорение вылуп/улучш дикого 💖, корм, скорлупа"),
            (0, 9, 5, "building_power", "сила зданий, сила эволюции, вылуп солдат"),
            (0, 17, 5, "building_power", "сила зданий, сила эволюции, вылуп солдат"),

            # Вторник - сбор ресурсов (00:05-23:05)
            (1, 1, 5, "building_power", "сила зданий, сила эволюции, вылуп солдат"),
            (1, 6, 5, "resource_bonus", "сила зданий ⭐, вылупление солдат, клетки"),
            (1, 14, 5, "resource_bonus", "сила зданий ⭐, вылупление солдат, клетки"),
            (1, 22, 5, "resource_bonus", "сила зданий ⭐, вылупление солдат, клетки"),

            # Среда - эволюция (00:05-23:05)
            (2, 1, 5, "evolution_bonus", "сила эволюции, сила зданий ⭐, вылупление солдат"),
            (2, 12, 5, "evolution_bonus", "сила эволюции 💖, ускор на эволюцию, останки животных"),
            (2, 20, 5, "evolution_bonus", "сила эволюции 💖, ускор на эволюцию, останки животных"),

            # Четверг - спецуслуги (00:05-23:05)
            (3, 4, 5, "special_services", "мут споры, яйца 💖, опыт, навыки"),
            (3, 12, 5, "special_services", "мут споры, яйца 💖, опыт, навыки"),
            (3, 20, 5, "special_services", "мут споры, яйца 💖, опыт, навыки"),

            # Пятница - выпущенные солдат (00:05-23:05)
            (4, 0, 5, "special_services", "мут споры, яйца 💖, опыт, навыки"),
            (4, 17, 5, "training_bonus", "сила зданий ⭐, вылупление солдат"),
            (4, 1, 5, "evolution_bonus", "сила эволюции, сила зданий, ускор на вылупление"),

            # Суббота - на выбор (00:05-23:05)
            (5, 1, 5, "training_bonus", "сила зданий ⭐, вылупление солдат"),
            (5, 9, 5, "training_bonus", "сила зданий ⭐, вылупление солдат"),
            (5, 17, 5, "training_bonus", "сила зданий ⭐, вылупление солдат"),

            # Воскресенье - сумм/район/стоп (00:05-23:05)
            (6, 1, 5, "training_bonus", "сила зданий ⭐, вылупление солдат"),
            (6, 4, 5, "wild_bonus", "ускорение вылуп/улучш дикого 💖, корм, скорлупа"),
            (6, 22, 5, "wild_bonus", "сила эволюции 💖, вылупление солдат, корм, скорлупа")
        ]

        self.prime_times = {}
        for day, hour, minute, action_type, bonus in default_actions:
            action = PrimeTimeAction(action_type, bonus, day, hour, minute)
            self._add_action(action)

    def _day_name_to_number(self, day_name: str) -> int:
        """Конвертация названия дня в номер (0=ПН, 6=ВС)"""
        day_mapping = {
            'monday': 0, 'понедельник': 0, 'пн': 0,
            'tuesday': 1, 'вторник': 1, 'вт': 1,
            'wednesday': 2, 'среда': 2, 'ср': 2,
            'thursday': 3, 'четверг': 3, 'чт': 3,
            'friday': 4, 'пятница': 4, 'пт': 4,
            'saturday': 5, 'суббота': 5, 'сб': 5,
            'sunday': 6, 'воскресенье': 6, 'вс': 6
        }
        return day_mapping.get(day_name.lower(), -1)

    def _parse_time(self, time_str: str) -> Tuple[int, int]:
        """Парсинг времени из строки в формате HH:MM"""
        time_str = time_str.strip()
        if ':' in time_str:
            hour_str, minute_str = time_str.split(':')
            return int(hour_str), int(minute_str)
        else:
            # Возможно формат только часы
            return int(time_str), 0

    def _parse_action_string(self, action_str: str) -> Tuple[str, str]:
        """Парсинг строки действия для извлечения типа и описания бонуса"""
        action_str = action_str.strip()

        # Определяем тип действия по ключевым словам
        if any(word in action_str.lower() for word in ['сила зданий', 'здани', 'постройк']):
            return 'building_power', action_str
        elif any(word in action_str.lower() for word in ['сила эволюции', 'эволюц']):
            return 'evolution_bonus', action_str
        elif any(word in action_str.lower() for word in ['вылуп', 'солдат', 'войск']):
            return 'training_bonus', action_str
        elif any(word in action_str.lower() for word in ['клетки', 'эссенция', 'ресурс']):
            return 'resource_bonus', action_str
        elif any(word in action_str.lower() for word in ['останки', 'животн']):
            return 'evolution_bonus', action_str
        elif any(word in action_str.lower() for word in ['споры', 'яйца', 'опыт', 'навыки']):
            return 'special_services', action_str
        elif any(word in action_str.lower() for word in ['дикого', 'корм', 'скорлуп']):
            return 'wild_bonus', action_str
        elif any(word in action_str.lower() for word in ['ускор', 'ускорени']):
            if 'эволюц' in action_str.lower():
                return 'evolution_bonus', action_str
            elif 'постройк' in action_str.lower():
                return 'building_power', action_str
            elif 'вылуп' in action_str.lower():
                return 'training_bonus', action_str
            else:
                return 'speedup_bonus', action_str
        else:
            return 'general_bonus', action_str

    def _add_action(self, action: PrimeTimeAction) -> None:
        """Добавление действия в словарь прайм-таймов"""
        if action.action_type not in self.prime_times:
            self.prime_times[action.action_type] = []
        self.prime_times[action.action_type].append(action)

    def _count_total_actions(self) -> int:
        """Подсчет общего количества прайм-таймов"""
        return sum(len(actions) for actions in self.prime_times.values())

    def get_current_prime_actions(self, target_time: Optional[datetime] = None) -> List[PrimeTimeAction]:
        """
        Получение текущих прайм-таймов для указанного времени
        ИСПРАВЛЕНО: Учитывает периоды обновления заданий

        Args:
            target_time: Время для проверки (по умолчанию - текущее)

        Returns:
            Список активных прайм-таймов
        """
        if target_time is None:
            target_time = datetime.now()

        # КРИТИЧНО: Проверяем период обновления заданий
        if self.is_maintenance_period(target_time):
            logger.debug(f"Период обновления {target_time.strftime('%H:%M')} - прайм-тайм не активен")
            return []

        current_day = target_time.weekday()  # 0=ПН, 6=ВС
        current_hour = target_time.hour
        current_minute = target_time.minute

        active_actions = []
        tolerance = self.settings['tolerance_minutes']

        for action_type, actions in self.prime_times.items():
            for action in actions:
                if (action.day_of_week == current_day and
                        action.hour == current_hour and
                        abs(action.minute - current_minute) <= tolerance):
                    active_actions.append(action)

        return active_actions

    def get_next_prime_window(self, action_types: List[str],
                              from_time: Optional[datetime] = None) -> Optional[Tuple[datetime, List[PrimeTimeAction]]]:
        """
        Получение следующего окна прайм-тайма для указанных типов действий
        ИСПРАВЛЕНО: Пропускает периоды обновления заданий

        Args:
            action_types: Список типов действий для поиска
            from_time: Время от которого искать (по умолчанию - текущее)

        Returns:
            Кортеж (время, список действий) или None если не найдено
        """
        if from_time is None:
            from_time = datetime.now()

        # Ищем ближайшие прайм-таймы в течение следующих 7 дней
        for days_ahead in range(8):  # Проверяем неделю вперед
            check_date = from_time + timedelta(days=days_ahead)
            day_of_week = check_date.weekday()

            # Получаем все действия для этого дня
            day_actions = []
            for action_type in action_types:
                if action_type in self.prime_times:
                    for action in self.prime_times[action_type]:
                        if action.day_of_week == day_of_week:
                            day_actions.append(action)

            # Сортируем по времени
            day_actions.sort(key=lambda a: (a.hour, a.minute))

            # Ищем подходящее время в этом дне
            for action in day_actions:
                action_time = check_date.replace(
                    hour=action.hour,
                    minute=action.minute,
                    second=0,
                    microsecond=0
                )

                # Если это время еще не прошло И не период обновления
                if action_time > from_time and not self.is_maintenance_period(action_time):
                    # Собираем все действия в это же время
                    concurrent_actions = [
                        a for a in day_actions
                        if a.hour == action.hour and a.minute == action.minute
                    ]
                    return action_time, concurrent_actions

        return None

    def should_wait_for_prime_time(self, action_types: List[str],
                                   max_wait_hours: Optional[float] = None) -> Tuple[bool, Optional[datetime]]:
        """
        Определение стоит ли ждать прайм-тайм для указанных действий
        ИСПРАВЛЕНО: Учитывает периоды обновления заданий

        Args:
            action_types: Типы действий для проверки
            max_wait_hours: Максимальное время ожидания в часах

        Returns:
            Кортеж (стоит_ждать, время_прайм_тайма)
        """
        if max_wait_hours is None:
            max_wait_hours = self.settings['max_wait_hours']

        next_window = self.get_next_prime_window(action_types)

        if not next_window:
            return False, None

        next_time, actions = next_window
        current_time = datetime.now()

        # КРИТИЧНО: Проверяем не в периоде ли обновления текущее время
        if self.is_maintenance_period(current_time):
            logger.debug("Сейчас период обновления - можно подождать до прайм-тайма")

        wait_time = (next_time - current_time).total_seconds() / 3600  # В часах

        if wait_time <= max_wait_hours:
            logger.info(f"Рекомендуется ждать прайм-тайм {wait_time:.1f}ч: {[a.action_type for a in actions]}")
            return True, next_time
        else:
            logger.debug(f"Прайм-тайм слишком далеко ({wait_time:.1f}ч), не ждем")
            return False, None

    def get_prime_actions_for_day(self, day_of_week: int) -> List[PrimeTimeAction]:
        """
        Получение всех прайм-таймов для указанного дня недели

        Args:
            day_of_week: День недели (0=ПН, 6=ВС)

        Returns:
            Список прайм-таймов для дня
        """
        day_actions = []

        for action_type, actions in self.prime_times.items():
            for action in actions:
                if action.day_of_week == day_of_week:
                    day_actions.append(action)

        # Сортируем по времени
        day_actions.sort(key=lambda a: (a.hour, a.minute))
        return day_actions

    def get_actions_by_type(self, action_type: str) -> List[PrimeTimeAction]:
        """Получение всех прайм-таймов для указанного типа действий"""
        return self.prime_times.get(action_type, [])

    def is_prime_time_active(self, action_types: List[str],
                             tolerance_minutes: Optional[int] = None) -> Tuple[bool, List[PrimeTimeAction]]:
        """
        Проверка активен ли сейчас прайм-тайм для указанных действий
        ИСПРАВЛЕНО: Учитывает периоды обновления заданий

        Args:
            action_types: Типы действий для проверки
            tolerance_minutes: Допуск в минутах

        Returns:
            Кортеж (активен, список_активных_действий)
        """
        if tolerance_minutes is None:
            tolerance_minutes = self.settings['tolerance_minutes']

        current_time = datetime.now()

        # КРИТИЧНО: Проверяем период обновления заданий
        if self.is_maintenance_period(current_time):
            logger.debug(f"Период обновления {current_time.strftime('%H:%M')} - прайм-тайм НЕ активен")
            return False, []

        active_actions = []

        for action_type in action_types:
            if action_type in self.prime_times:
                for action in self.prime_times[action_type]:
                    # Проверяем день недели
                    if action.day_of_week != current_time.weekday():
                        continue

                    # Проверяем время с допуском
                    action_time = current_time.replace(
                        hour=action.hour,
                        minute=action.minute,
                        second=0,
                        microsecond=0
                    )

                    time_diff = abs((current_time - action_time).total_seconds() / 60)

                    if time_diff <= tolerance_minutes:
                        active_actions.append(action)

        return len(active_actions) > 0, active_actions

    def get_priority_bonus_for_action(self, action_type: str) -> int:
        """
        Получение бонуса приоритета для действия в прайм-тайм
        ИСПРАВЛЕНО: Учитывает периоды обновления заданий

        Args:
            action_type: Тип действия

        Returns:
            Бонус приоритета (0 если не в прайм-тайм или период обновления)
        """
        # КРИТИЧНО: Проверяем период обновления заданий
        if self.is_maintenance_period():
            return 0

        is_active, active_actions = self.is_prime_time_active([action_type])

        if is_active:
            # Возвращаем бонус из настроек или по умолчанию
            priority_bonuses = self.settings.get('priority_bonuses', {
                'building_power': 200,
                'evolution_bonus': 150,
                'training_bonus': 100,
                'resource_bonus': 100,
                'special_services': 80,
                'wild_bonus': 60,
                'speedup_bonus': 50,
                'general_bonus': 40
            })
            return priority_bonuses.get(action_type, 50)

        return 0

    def get_status_summary(self) -> Dict[str, Any]:
        """Получение сводки по статусу прайм-таймов"""
        current_time = datetime.now()
        current_actions = self.get_current_prime_actions()
        is_maintenance = self.is_maintenance_period()

        # Ищем ближайшие прайм-таймы
        all_action_types = list(self.prime_times.keys())
        next_window = self.get_next_prime_window(all_action_types)

        summary = {
            'total_prime_times': self._count_total_actions(),
            'action_types': list(self.prime_times.keys()),
            'current_active': len(current_actions),
            'current_actions': [str(action) for action in current_actions],
            'is_maintenance_period': is_maintenance,
            'current_time': current_time.strftime('%H:%M'),
            'next_prime_time': None,
            'next_actions': []
        }

        if next_window:
            next_time, next_actions = next_window
            summary['next_prime_time'] = next_time.strftime('%Y-%m-%d %H:%M')
            summary['next_actions'] = [str(action) for action in next_actions]

        return summary

    def save_prime_times_to_database(self, database) -> bool:
        """
        Сохранение прайм-таймов в базу данных

        Args:
            database: Экземпляр Database для сохранения

        Returns:
            True если сохранение успешно
        """
        try:
            with database.get_connection() as conn:
                cursor = conn.cursor()

                # Очищаем старые данные
                cursor.execute('DELETE FROM prime_times')

                # Загружаем новые данные
                total_saved = 0
                for action_type, actions in self.prime_times.items():
                    for action in actions:
                        cursor.execute('''
                            INSERT INTO prime_times 
                            (day_of_week, hour, minute, action_type, bonus_description)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (
                            action.day_of_week,
                            action.hour,
                            action.minute,
                            action.action_type,
                            action.bonus_description
                        ))
                        total_saved += 1

                conn.commit()

            logger.success(f"Сохранено {total_saved} прайм-таймов в базу данных")
            return True

        except Exception as e:
            logger.error(f"Ошибка сохранения прайм-таймов в БД: {e}")
            return False


# Глобальный экземпляр менеджера прайм-таймов
prime_time_manager = PrimeTimeManager()