import asyncio
import json
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, executor, types
from tabulate import tabulate

import connector
from device import get_name, get_route_manager_name, get_route_pos, get_route_max, get_last_updated
from run_args import get_args
import traceback

args = get_args()
log = logging.getLogger('__name__')


def run():
    
    bot = Bot(args.telegram_token)
    dp = Dispatcher(bot)
    loop = asyncio.get_event_loop()
    @dp.message_handler(commands=['status'])
    async def subscribe(message: types.Message):
        with open('servers.json') as f:
            servers_config_json = json.load(f)
            for server in servers_config_json: 
                if message.from_user.id == int(server['telegram_channel_id']):#проверка по id чата 
                    await build_status_response(message, server, True)

    @dp.message_handler(commands=['status_all'])
    async def subscribe(message: types.Message):
        with open('servers.json') as f:
            servers_config_json = json.load(f)
            for server in servers_config_json: 
                if message.from_user.id == int(server['telegram_channel_id']):
                    await build_status_response(message, server, False)
                    
    async def alert_thread():
        try:
            duration_before_alert = args.duration_before_alert
            delay_between_checks = args.delay_between_checks
            discord_post_data = {
                "username": "MAD Alert",
                "avatar_url": "https://www.iconsdb.com/icons/preview/red/exclamation-xxl.png",
                "embeds": [{
                    "title": f"ERROR - No data for {duration_before_alert} minutes!",
                    "color": 16711680,
                    "description": "PLACEHOLDER",
                    "footer": {
                        "text": "PLACEHOLDER"
                    }
                }]
            }
            log.info("Starting Device Checker Script")
            while True:
                
                with open('servers.json') as servers_json:
                    servers_config_json = json.load(servers_json)
                    for server in servers_config_json:
                        description_initial = f"<u>{server['name']}</u>\n"
                        description = description_initial
                        discord_post_data['embeds'][0]['description'] = description_initial
                        log.info(f"Starting check on {server['ip']}")
                        r = connector.get_status(server)

                        if r is None:
                            await bot.send_message(server['telegram_channel_id'], f"\U0001F198<b>Server unavailable</b>\nServer {server['name']} is not available to get status", parse_mode = 'HTML')
                            r = []

                        r.sort(key=get_name)
                        for device in r or []:
                            device_origin = str(get_name(device)).title()
                            device_last_proto_datetime = get_last_updated(device)
                            routemanager = str(get_route_manager_name(device)).title()

                            log.info(f"Checking {device_origin} device")
                            log.debug(device)
                            if routemanager.lower() != 'idle':
                                # TODO Remove the 'None' check once MAD has the change to remove 'None' from /get_status
                                if device_last_proto_datetime is not None and device_last_proto_datetime != 'None' and device_last_proto_datetime > 0:
                                    parsed_device_last_proto_datetime = datetime.fromtimestamp(device_last_proto_datetime)
                                    latest_acceptable_datetime = (datetime.now() - timedelta(minutes=duration_before_alert))
                                    log.debug(f"{device_origin} Last Proto Date Time: {parsed_device_last_proto_datetime}")
                                    log.debug(f"{device_origin} Last Acceptable Time: {latest_acceptable_datetime}")

                                    if parsed_device_last_proto_datetime < latest_acceptable_datetime:
                                        log.info(f"{device_origin} breached the time threshold")
                                        description = description + f"{device_origin.capitalize()} - {routemanager} -> (" \
                                                                    f"Last Received: {parsed_device_last_proto_datetime.strftime('%H:%M')})\n "
                                        log.debug(f"Current description: {description}")
                                    else:
                                        log.info(f"{device_origin} did not breach the time threshold")
                                else:
                                    description = description + f"{device_origin.capitalize()} (Last Received: Not known)\n"
                            else:
                                log.info("Ignoring as device is set to idle")

                        if len(description) > len(description_initial):
                            # if 'alert_role_id' in server:
                            #     discord_post_data['content'] = f"Problem on {server['name']} <@&{server['alert_role_id']}>"
                            # elif 'alert_user_id' in server:
                            #     discord_post_data['content'] = f"Problem on {server['name']} <@{server['alert_user_id']}>"

                            discord_post_data['embeds'][0]['description'] = description

                            time_of_next_check = (datetime.now() + timedelta(minutes=delay_between_checks)).strftime('%H:%M')

                            discord_post_data['embeds'][0]['footer']['text'] = f"Next check will be at {time_of_next_check}"

                            log.debug(discord_post_data)
                            # log.info("Sending alert to Discord as one or more devices has exceeded the threshold")
                            log.info("Sending alert to Telegram as one or more devices has exceeded the threshold")
                            titel = discord_post_data['embeds'][0]['title']
                            footer = discord_post_data['embeds'][0]['footer']['text']
                            await bot.send_message(server['telegram_channel_id'],f"\U00002757<b>{titel}</b>\n{description}<code>{footer}</code>", parse_mode= 'HTML')

                            # response = requests.post(
                            #     server['webhook'], data=json.dumps(discord_post_data),
                            #     headers={'Content-Type': 'application/json'}
                            # )

                            # log.debug(response)
                            # if response.status_code != 204:
                            #     log.error(
                            #         'Post to Discord webhook returned an error %s, the response is:\n%s'
                            #         % (response.status_code, response.text)
                            #     )
                            # else:
                            #     log.debug("Message posted to Discord with success")
                        else:
                            log.debug("There is no errors to report, going to sleep")

                log.info("All device checks completed, going to sleep")
                # time.sleep(60 * delay_between_checks)
                await asyncio.sleep(60*delay_between_checks)
                
        except Exception as ex:
            traceback.print_exc()
            log.error('Issues in the checker tread exception was: ' + str(ex))


            # print("allest")
                # await bot.send_message(332991826,"ssssss")
            # await asyncio.sleep(10)

    # executor.start_polling(dp, skip_updates=True)

    loop.create_task(alert_thread())
    executor.start_polling(dp, skip_updates=True)
        

def build_status_response(message, server, return_only_failed: bool):
    any_error_found = False

    server_name = server['name']
    table_header = ['Origin', 'Route', 'Pos', 'Time']
    table_contents = []

    log.info(f"Status request received for {server_name}")
    log.debug("Calling /get_status for current status")
    device_status_response = connector.get_status(server,True)

    if device_status_response is None:
        return message.answer(f"\U0001F198<b>Server unavailable</b>\nServer {server['name']} is not available to get status", parse_mode= 'HTML')  
    
    # Sort by name ascending
    device_status_response.sort(key=get_name)

    for device in device_status_response or []:
        device_failed = False
        table_before = tabulate(table_contents, headers=table_header)
        route_manager = get_route_manager_name(device) if get_route_manager_name(device) is not None else ''
        origin = get_name(device) if get_name(device) is not None else ''
        route_pos = get_route_pos(device) if get_route_pos(device) is not None else '?'
        route_max = get_route_max(device) if get_route_max(device) is not None else '?'
        last_proto_date_time = get_last_updated(device) if get_last_updated(device) is not None else ''
        number_front_chars = 6
        number_end_chars = 5

        try:
            datetime_from_status_json = datetime.fromtimestamp(last_proto_date_time)
            formatted_device_last_proto_time = datetime_from_status_json.strftime("%H:%M")
            latest_acceptable_datetime = (datetime.now() - timedelta(minutes=args.duration_before_alert))
            log.debug(f"{origin} Last Proto Date Time: {datetime_from_status_json}")
            log.debug(f"{origin} Last Acceptable Time: {latest_acceptable_datetime}")

            if datetime_from_status_json < latest_acceptable_datetime:
                log.info(f"{str(origin)} failed")
                device_failed = True
                any_error_found = True

        except Exception as e:
            log.info(f"{e} {origin} {route_manager}")
            any_error_found = True
            device_failed = True
            formatted_device_last_proto_time = 'Unkwn'

        if args.trim_table_content:
            if len(route_manager) > (number_front_chars + number_end_chars):
                route_manager = f"{route_manager[:number_front_chars]}..{route_manager[-number_end_chars:]}"
            if len(origin) > (number_front_chars + number_end_chars):
                origin = f"{origin[:number_front_chars]}..{origin[-number_end_chars:]}"

        if (return_only_failed and device_failed and route_manager.lower() != "idle") or not return_only_failed:
            table_contents.append([origin,
                                    route_manager,
                                    f"{route_pos}/{route_max}",
                                    formatted_device_last_proto_time
                                    ])

        table_after = tabulate(table_contents, headers=table_header)

        table_before_len = len(table_before)
        table_after_len = len(table_after)

        log.debug(f"{table_before_len} and after {table_after_len}")
        log.debug("Error found: " + str(any_error_found))

        # color = 0xFF6E6E if any_error_found is True else 0x98FB98
 

        if table_before_len > 2000:
            log.error("Table before exceeds 2000 word count. How did this happened?")
            return

        if table_after_len > 2000:
            log.info("Table size was greater than 2000. Commence table split.")
            log.debug(table_before)
            return message.answer("Table size too much, sorry") #TODO something

        log.debug(f"Sending status table for {server_name}")
        table_to_send = tabulate(table_contents, headers=table_header)

        log.debug(table_to_send)

        if len(table_contents) > 0:
            embed = table_to_send
        else:

            embed = "No devices need your attention"

        # embed.set_thumbnail(url=iconURL)
        # embed.set_author(name=server['name'], url='', icon_url='')
        # await message.channel.send(embed=embed)
        
        return message.answer("<b>"+server['name'] +"</b>\n" +"<pre>" + embed + "</pre>" , parse_mode= 'HTML')       

