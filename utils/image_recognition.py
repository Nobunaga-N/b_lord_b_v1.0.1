"""
Модуль для распознавания изображений и поиска шаблонов на экране.
Использует OpenCV для поиска элементов интерфейса игры.
"""

import time
from typing import Optional, Tuple, List, Union
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from loguru import logger


class TemplateMatchResult:
    """Результат поиска шаблона"""

    def __init__(self, found: bool, center: Optional[Tuple[int, int]] = None,
                 confidence: float = 0.0, bbox: Optional[Tuple[int, int, int, int]] = None):
        self.found = found
        self.center = center  # Центр найденного шаблона
        self.confidence = confidence  # Уверенность в совпадении (0-1)
        self.bbox = bbox  # Прямоугольник: (x, y, width, height)

    def __bool__(self):
        return self.found

    def __str__(self):
        if self.found:
            return f"TemplateMatch(center={self.center}, confidence={self.confidence:.3f})"
        else:
            return "TemplateMatch(not found)"


class ImageRecognition:
    """Класс для распознавания изображений и поиска шаблонов"""

    def __init__(self, templates_dir: str = "data/templates"):
        """
        Инициализация модуля распознавания

        Args:
            templates_dir: Путь к папке с шаблонами изображений
        """
        self.templates_dir = Path(templates_dir)
        self.templates_dir.mkdir(parents=True, exist_ok=True)

        # Кэш загруженных шаблонов
        self.template_cache = {}

        logger.info(f"Инициализирован ImageRecognition, папка шаблонов: {self.templates_dir}")

    def load_template(self, template_name: str) -> Optional[np.ndarray]:
        """
        Загружает шаблон изображения

        Args:
            template_name: Имя файла шаблона (с расширением или без)

        Returns:
            OpenCV изображение или None если не найдено
        """
        # Проверяем кэш
        if template_name in self.template_cache:
            return self.template_cache[template_name]

        # Пробуем разные расширения если не указано
        if not Path(template_name).suffix:
            extensions = ['.png', '.jpg', '.jpeg', '.bmp']
            template_paths = [self.templates_dir / f"{template_name}{ext}" for ext in extensions]
        else:
            template_paths = [self.templates_dir / template_name]

        for template_path in template_paths:
            if template_path.exists():
                try:
                    # Загружаем изображение
                    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
                    if template is not None:
                        # Сохраняем в кэш
                        self.template_cache[template_name] = template
                        logger.debug(f"Загружен шаблон: {template_path}")
                        return template
                except Exception as e:
                    logger.warning(f"Ошибка загрузки шаблона {template_path}: {e}")

        logger.error(f"Шаблон не найден: {template_name}")
        return None

    def pil_to_cv2(self, pil_image: Image.Image) -> np.ndarray:
        """
        Конвертирует PIL изображение в OpenCV формат

        Args:
            pil_image: PIL изображение

        Returns:
            OpenCV изображение в формате BGR
        """
        # Конвертируем PIL в RGB, затем в numpy array
        rgb_image = pil_image.convert('RGB')
        cv2_image = np.array(rgb_image)

        # OpenCV использует BGR, а PIL RGB, поэтому меняем каналы
        cv2_image = cv2.cvtColor(cv2_image, cv2.COLOR_RGB2BGR)

        return cv2_image

    def find_template(self, screenshot: Union[Image.Image, np.ndarray],
                      template_name: str, threshold: float = 0.8,
                      method: int = cv2.TM_CCOEFF_NORMED) -> TemplateMatchResult:
        """
        Ищет шаблон на скриншоте

        Args:
            screenshot: Скриншот (PIL Image или OpenCV array)
            template_name: Имя шаблона для поиска
            threshold: Порог уверенности (0-1)
            method: Метод сравнения OpenCV

        Returns:
            Результат поиска шаблона
        """
        try:
            # Загружаем шаблон
            template = self.load_template(template_name)
            if template is None:
                return TemplateMatchResult(False)

            # Конвертируем скриншот в OpenCV формат если нужно
            if isinstance(screenshot, Image.Image):
                image = self.pil_to_cv2(screenshot)
            else:
                image = screenshot.copy()

            # Выполняем поиск шаблона
            result = cv2.matchTemplate(image, template, method)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

            # Для TM_CCOEFF_NORMED и TM_CCORR_NORMED используем max_val
            if method in [cv2.TM_CCOEFF_NORMED, cv2.TM_CCORR_NORMED]:
                confidence = max_val
                match_loc = max_loc
            else:
                confidence = 1.0 - min_val  # Инвертируем для других методов
                match_loc = min_loc

            # Проверяем порог
            if confidence >= threshold:
                h, w = template.shape[:2]

                # Вычисляем центр найденного шаблона
                center_x = match_loc[0] + w // 2
                center_y = match_loc[1] + h // 2
                center = (center_x, center_y)

                # Прямоугольник вокруг найденного шаблона
                bbox = (match_loc[0], match_loc[1], w, h)

                logger.debug(f"Шаблон '{template_name}' найден в {center} с уверенностью {confidence:.3f}")
                return TemplateMatchResult(True, center, confidence, bbox)
            else:
                logger.debug(f"Шаблон '{template_name}' не найден (уверенность {confidence:.3f} < {threshold})")
                return TemplateMatchResult(False, confidence=confidence)

        except Exception as e:
            logger.error(f"Ошибка при поиске шаблона '{template_name}': {e}")
            return TemplateMatchResult(False)

    def find_all_templates(self, screenshot: Union[Image.Image, np.ndarray],
                           template_name: str, threshold: float = 0.8) -> List[TemplateMatchResult]:
        """
        Находит все вхождения шаблона на скриншоте

        Args:
            screenshot: Скриншот для поиска
            template_name: Имя шаблона
            threshold: Порог уверенности

        Returns:
            Список всех найденных совпадений
        """
        try:
            template = self.load_template(template_name)
            if template is None:
                return []

            if isinstance(screenshot, Image.Image):
                image = self.pil_to_cv2(screenshot)
            else:
                image = screenshot.copy()

            # Выполняем поиск
            result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
            h, w = template.shape[:2]

            # Находим все совпадения выше порога
            locations = np.where(result >= threshold)
            matches = []

            for pt in zip(*locations[::-1]):  # Переворачиваем координаты
                confidence = result[pt[1], pt[0]]
                center = (pt[0] + w // 2, pt[1] + h // 2)
                bbox = (pt[0], pt[1], w, h)

                matches.append(TemplateMatchResult(True, center, confidence, bbox))

            logger.debug(f"Найдено {len(matches)} вхождений шаблона '{template_name}'")
            return matches

        except Exception as e:
            logger.error(f"Ошибка при поиске всех шаблонов '{template_name}': {e}")
            return []

    def wait_for_template(self, controller, template_name: str,
                          timeout: float = 30.0, check_interval: float = 1.0,
                          threshold: float = 0.8) -> TemplateMatchResult:
        """
        Ожидает появления шаблона на экране

        Args:
            controller: ADBController для получения скриншотов
            template_name: Имя шаблона для ожидания
            timeout: Максимальное время ожидания в секундах
            check_interval: Интервал между проверками в секундах
            threshold: Порог уверенности

        Returns:
            Результат поиска шаблона
        """
        logger.info(f"Ожидаем появления шаблона '{template_name}' (таймаут: {timeout}с)")

        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # Получаем скриншот
                screenshot = controller.screenshot()
                if screenshot is None:
                    logger.warning("Не удалось получить скриншот для поиска шаблона")
                    time.sleep(check_interval)
                    continue

                # Ищем шаблон
                result = self.find_template(screenshot, template_name, threshold)

                if result.found:
                    elapsed = time.time() - start_time
                    logger.success(f"Шаблон '{template_name}' найден через {elapsed:.1f}с")
                    return result

                # Ждем перед следующей проверкой
                time.sleep(check_interval)

            except Exception as e:
                logger.error(f"Ошибка при ожидании шаблона '{template_name}': {e}")
                time.sleep(check_interval)

        elapsed = time.time() - start_time
        logger.warning(f"Шаблон '{template_name}' не найден за {elapsed:.1f}с")
        return TemplateMatchResult(False)

    def click_template(self, controller, template_name: str,
                       threshold: float = 0.8, offset: Tuple[int, int] = (0, 0)) -> bool:
        """
        Находит шаблон и кликает по нему

        Args:
            controller: ADBController для выполнения клика
            template_name: Имя шаблона для поиска
            threshold: Порог уверенности
            offset: Смещение клика относительно центра шаблона

        Returns:
            True если клик выполнен успешно, False иначе
        """
        try:
            # Получаем скриншот
            screenshot = controller.screenshot()
            if screenshot is None:
                logger.error("Не удалось получить скриншот для поиска шаблона")
                return False

            # Ищем шаблон
            result = self.find_template(screenshot, template_name, threshold)

            if not result.found:
                logger.warning(f"Шаблон '{template_name}' не найден для клика")
                return False

            # Вычисляем координаты клика с учетом смещения
            click_x = result.center[0] + offset[0]
            click_y = result.center[1] + offset[1]

            # Выполняем клик
            if controller.tap(click_x, click_y):
                logger.info(f"Клик по шаблону '{template_name}' в ({click_x}, {click_y})")
                return True
            else:
                logger.error(f"Не удалось выполнить клик по шаблону '{template_name}'")
                return False

        except Exception as e:
            logger.error(f"Ошибка при клике по шаблону '{template_name}': {e}")
            return False

    def save_debug_image(self, screenshot: Union[Image.Image, np.ndarray],
                         matches: List[TemplateMatchResult],
                         output_path: str, template_name: str = "") -> bool:
        """
        Сохраняет отладочное изображение с отмеченными найденными шаблонами

        Args:
            screenshot: Исходный скриншот
            matches: Список найденных совпадений
            output_path: Путь для сохранения
            template_name: Имя шаблона для подписи

        Returns:
            True если сохранено успешно, False иначе
        """
        try:
            if isinstance(screenshot, Image.Image):
                image = self.pil_to_cv2(screenshot)
            else:
                image = screenshot.copy()

            # Отмечаем найденные шаблоны
            for match in matches:
                if match.found and match.bbox:
                    x, y, w, h = match.bbox

                    # Рисуем прямоугольник
                    cv2.rectangle(image, (x, y), (x + w, y + h), (0, 255, 0), 2)

                    # Добавляем точку в центре
                    cv2.circle(image, match.center, 5, (0, 0, 255), -1)

                    # Добавляем текст с уверенностью
                    confidence_text = f"{match.confidence:.3f}"
                    cv2.putText(image, confidence_text, (x, y - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

            # Сохраняем изображение
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(output_path, image)

            logger.debug(f"Отладочное изображение сохранено: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Ошибка при сохранении отладочного изображения: {e}")
            return False


# Глобальный экземпляр для удобства использования
image_recognition = ImageRecognition()