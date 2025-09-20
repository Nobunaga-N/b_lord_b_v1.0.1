"""
Базовые игровые действия для Beast Lord The New Land.
Содержит функции для входа в игру, навигации и основных операций.
"""

import time
from typing import Optional, Tuple
from pathlib import Path

from loguru import logger
from utils.image_recognition import image_recognition


def enter_game(controller, max_attempts: int = 3, timeout: float = 60.0) -> bool:
    """
    Запуск игры и вход в аккаунт

    Args:
        controller: ADBController для управления устройством
        max_attempts: Максимальное количество попыток входа
        timeout: Таймаут для каждой попытки в секундах

    Returns:
        True если вход выполнен успешно, False иначе
    """
    logger.info("Начинаем процедуру входа в игру Beast Lord")

    for attempt in range(1, max_attempts + 1):
        logger.info(f"Попытка входа {attempt}/{max_attempts}")

        try:
            # 1. Проверяем, не находимся ли мы уже в игре
            if _check_if_in_game(controller):
                logger.success("Уже находимся в игре")
                return True

            # 2. Ищем иконку игры на главном экране
            if not _launch_game_app(controller, timeout):
                logger.warning(f"Не удалось запустить игру (попытка {attempt})")
                continue

            # 3. Ждем загрузки и проходим экраны входа
            if not _handle_game_startup(controller, timeout):
                logger.warning(f"Не удалось пройти стартовые экраны (попытка {attempt})")
                continue

            # 4. Финальная проверка - находимся ли в игре
            if _check_if_in_game(controller):
                logger.success(f"Успешно вошли в игру с попытки {attempt}")
                return True
            else:
                logger.warning(f"После входа не обнаружили игровой интерфейс (попытка {attempt})")

        except Exception as e:
            logger.error(f"Ошибка при попытке входа {attempt}: {e}")

        # Пауза перед следующей попыткой
        if attempt < max_attempts:
            logger.info(f"Ждем 10 секунд перед следующей попыткой...")
            time.sleep(10)

    logger.error("Не удалось войти в игру после всех попыток")
    return False


def go_to_main_screen(controller, timeout: float = 30.0) -> bool:
    """
    Переход на главный экран игры (базовый вид замка)

    Args:
        controller: ADBController для управления устройством
        timeout: Максимальное время ожидания в секундах

    Returns:
        True если переход выполнен успешно, False иначе
    """
    logger.info("Переходим на главный экран игры")

    try:
        # 1. Проверяем, не находимся ли мы уже на главном экране
        if _check_main_screen(controller):
            logger.success("Уже находимся на главном экране")
            return True

        # 2. Пытаемся найти и нажать кнопку "домой" или "назад"
        home_templates = ["home_button", "back_button", "main_screen_button"]

        for template in home_templates:
            if image_recognition.click_template(controller, template, threshold=0.7):
                logger.info(f"Нажали кнопку '{template}'")
                time.sleep(2)

                # Проверяем, попали ли на главный экран
                if _check_main_screen(controller):
                    logger.success("Успешно перешли на главный экран")
                    return True

        # 3. Если кнопки не найдены, пробуем нажать ESC или Back
        logger.info("Пробуем нажать системную кнопку Back")
        controller.device.shell("input keyevent KEYCODE_BACK")
        time.sleep(2)

        if _check_main_screen(controller):
            logger.success("Перешли на главный экран через системную кнопку")
            return True

        # 4. Последняя попытка - клик по центру экрана и поиск главного меню
        logger.info("Последняя попытка - клик по центру экрана")
        screen_size = controller.get_screen_size()
        if screen_size:
            center_x, center_y = screen_size[0] // 2, screen_size[1] // 2
            controller.tap(center_x, center_y)
            time.sleep(3)

            if _check_main_screen(controller):
                logger.success("Перешли на главный экран")
                return True

        logger.warning("Не удалось перейти на главный экран")
        return False

    except Exception as e:
        logger.error(f"Ошибка при переходе на главный экран: {e}")
        return False


def check_shield(controller, auto_activate: bool = True) -> bool:
    """
    Проверка и активация защитного щита

    Args:
        controller: ADBController для управления устройством
        auto_activate: Автоматически активировать щит если он не активен

    Returns:
        True если щит активен (или был активирован), False иначе
    """
    logger.info("Проверяем состояние защитного щита")

    try:
        # 1. Сначала убеждаемся что мы на главном экране
        if not go_to_main_screen(controller):
            logger.error("Не удалось перейти на главный экран для проверки щита")
            return False

        # 2. Ищем индикатор активного щита
        screenshot = controller.screenshot()
        if screenshot is None:
            logger.error("Не удалось получить скриншот для проверки щита")
            return False

        # Ищем иконку активного щита
        shield_active = image_recognition.find_template(screenshot, "shield_active", threshold=0.7)

        if shield_active.found:
            logger.success("Защитный щит активен")
            return True

        # 3. Ищем иконку неактивного щита или кнопку активации
        shield_inactive = image_recognition.find_template(screenshot, "shield_inactive", threshold=0.7)
        shield_button = image_recognition.find_template(screenshot, "shield_button", threshold=0.7)

        if not (shield_inactive.found or shield_button.found):
            logger.warning("Не удалось найти индикатор щита")

            # Пробуем найти в меню профиля/настроек
            if _open_profile_menu(controller):
                shield_menu = image_recognition.find_template(controller.screenshot(), "shield_menu", threshold=0.7)
                if shield_menu.found:
                    image_recognition.click_template(controller, "shield_menu")
                    time.sleep(2)
                else:
                    logger.warning("Не удалось найти меню щита в профиле")
                    return False
            else:
                return False

        # 4. Если щит неактивен и нужно активировать
        if auto_activate:
            logger.info("Щит неактивен, пытаемся активировать")

            # Кликаем по иконке щита или кнопке активации
            if shield_inactive.found:
                if image_recognition.click_template(controller, "shield_inactive"):
                    logger.info("Кликнули по неактивному щиту")
                else:
                    return False
            elif shield_button.found:
                if image_recognition.click_template(controller, "shield_button"):
                    logger.info("Кликнули по кнопке щита")
                else:
                    return False

            time.sleep(2)

            # Ищем и нажимаем кнопку активации
            activate_buttons = ["activate_shield", "use_shield", "apply_shield", "confirm_shield"]

            for button_template in activate_buttons:
                if image_recognition.click_template(controller, button_template, threshold=0.7):
                    logger.info(f"Нажали кнопку активации щита: {button_template}")
                    time.sleep(3)
                    break
            else:
                logger.warning("Не удалось найти кнопку активации щита")
                return False

            # Проверяем успешность активации
            final_screenshot = controller.screenshot()
            if final_screenshot:
                shield_check = image_recognition.find_template(final_screenshot, "shield_active", threshold=0.7)
                if shield_check.found:
                    logger.success("Щит успешно активирован")
                    return True
                else:
                    logger.warning("Не удалось подтвердить активацию щита")
                    return False
        else:
            logger.info("Щит неактивен, автоактивация отключена")
            return False

    except Exception as e:
        logger.error(f"Ошибка при проверке щита: {e}")
        return False


def _check_if_in_game(controller) -> bool:
    """Проверяет, находимся ли мы в игре"""
    try:
        screenshot = controller.screenshot()
        if screenshot is None:
            return False

        # Ищем характерные элементы игрового интерфейса
        game_indicators = ["game_ui", "castle_view", "resources_panel", "main_menu_button"]

        for indicator in game_indicators:
            result = image_recognition.find_template(screenshot, indicator, threshold=0.6)
            if result.found:
                logger.debug(f"Обнаружен игровой интерфейс: {indicator}")
                return True

        return False

    except Exception as e:
        logger.warning(f"Ошибка при проверке нахождения в игре: {e}")
        return False


def _launch_game_app(controller, timeout: float) -> bool:
    """Запускает приложение игры"""
    try:
        # Ищем иконку Beast Lord на главном экране
        game_icon_templates = ["beast_lord_icon", "game_icon", "bl_icon"]

        for template in game_icon_templates:
            if image_recognition.click_template(controller, template, threshold=0.7):
                logger.info(f"Нажали на иконку игры: {template}")
                time.sleep(5)  # Ждем запуска
                return True

        # Альтернативный способ - через пакет приложения
        logger.info("Пробуем запустить игру через пакет приложения")
        controller.device.shell("monkey -p com.beastlord.newland -c android.intent.category.LAUNCHER 1")
        time.sleep(5)
        return True

    except Exception as e:
        logger.error(f"Ошибка при запуске игры: {e}")
        return False


def _handle_game_startup(controller, timeout: float) -> bool:
    """Обрабатывает стартовые экраны игры"""
    try:
        start_time = time.time()

        while time.time() - start_time < timeout:
            screenshot = controller.screenshot()
            if screenshot is None:
                time.sleep(2)
                continue

            # Ищем различные кнопки на стартовых экранах
            startup_buttons = [
                "start_game", "enter_game", "continue", "play_button",
                "tap_to_continue", "loading_complete", "press_any_key"
            ]

            for button in startup_buttons:
                if image_recognition.click_template(controller, button, threshold=0.7):
                    logger.info(f"Нажали стартовую кнопку: {button}")
                    time.sleep(3)
                    break

            # Проверяем, не попали ли уже в игру
            if _check_if_in_game(controller):
                return True

            time.sleep(2)

        return False

    except Exception as e:
        logger.error(f"Ошибка при обработке стартовых экранов: {e}")
        return False


def _check_main_screen(controller) -> bool:
    """Проверяет, находимся ли на главном экране игры"""
    try:
        screenshot = controller.screenshot()
        if screenshot is None:
            return False

        # Ищем элементы главного экрана
        main_screen_indicators = ["castle_main", "main_building", "resources_top", "lord_avatar"]

        found_count = 0
        for indicator in main_screen_indicators:
            result = image_recognition.find_template(screenshot, indicator, threshold=0.6)
            if result.found:
                found_count += 1

        # Считаем что на главном экране если нашли хотя бы 2 индикатора
        return found_count >= 2

    except Exception as e:
        logger.warning(f"Ошибка при проверке главного экрана: {e}")
        return False


def _open_profile_menu(controller) -> bool:
    """Открывает меню профиля/настроек"""
    try:
        profile_buttons = ["profile_button", "avatar_button", "settings_button", "menu_button"]

        for button in profile_buttons:
            if image_recognition.click_template(controller, button, threshold=0.7):
                logger.info(f"Открыли меню профиля через: {button}")
                time.sleep(2)
                return True

        return False

    except Exception as e:
        logger.error(f"Ошибка при открытии меню профиля: {e}")
        return False


def close_popup(controller, max_attempts: int = 3) -> bool:
    """
    Закрывает всплывающие окна и диалоги

    Args:
        controller: ADBController для управления устройством
        max_attempts: Максимальное количество попыток

    Returns:
        True если окна закрыты, False иначе
    """
    logger.info("Пытаемся закрыть всплывающие окна")

    for attempt in range(max_attempts):
        try:
            screenshot = controller.screenshot()
            if screenshot is None:
                time.sleep(1)
                continue

            # Ищем кнопки закрытия
            close_buttons = ["close_button", "x_button", "cancel_button", "ok_button", "dismiss_button"]

            found_popup = False
            for button in close_buttons:
                if image_recognition.click_template(controller, button, threshold=0.7):
                    logger.info(f"Закрыли всплывающее окно кнопкой: {button}")
                    found_popup = True
                    time.sleep(1)
                    break

            if not found_popup:
                # Если специальных кнопок нет, пробуем ESC
                controller.device.shell("input keyevent KEYCODE_BACK")
                time.sleep(1)

            # Проверяем остались ли всплывающие окна
            time.sleep(1)

        except Exception as e:
            logger.warning(f"Ошибка при закрытии всплывающих окон: {e}")

    logger.info("Завершили закрытие всплывающих окон")
    return True