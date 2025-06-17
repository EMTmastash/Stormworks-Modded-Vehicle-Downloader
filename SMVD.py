import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import os
import re
import requests
import xml.etree.ElementTree as ET # Still needed to validate XML structure
import configparser
import threading
import queue
import traceback

CONFIG_FILE = "sw_installer_config.ini"
STORMWORKS_APP_ID = "573090"

class StormworksInstallerApp:
    def __init__(self, root_window):
        self.root = root_window
        self.root.title("Stormworks Gist Vehicle Installer")
        self.root.geometry("600x500")

        self.config = configparser.ConfigParser()
        self.steam_workshop_base_path = tk.StringVar()
        self.dummy_workshop_url = tk.StringVar()
        self.gist_url = tk.StringVar()

        self._setup_ui()

        self.q = queue.Queue()
        self.load_config_values()
        self.ensure_initial_config()

        if hasattr(self.root, 'winfo_exists') and self.root.winfo_exists():
            self.process_task_queue()

    def _setup_ui(self):
        path_frame = tk.LabelFrame(self.root, text="Configuration", padx=5, pady=5)
        path_frame.pack(pady=10, padx=10, fill="x")
        tk.Label(path_frame, text="Stormworks Workshop Content Path:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        self.path_entry = tk.Entry(path_frame, textvariable=self.steam_workshop_base_path, width=50, state="readonly")
        self.path_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        self.browse_button = tk.Button(path_frame, text="Browse...", command=self.select_workshop_folder)
        self.browse_button.grid(row=0, column=2, padx=5, pady=2)
        path_frame.grid_columnconfigure(1, weight=1)

        input_frame = tk.LabelFrame(self.root, text="Vehicle Installation", padx=5, pady=5)
        input_frame.pack(pady=10, padx=10, fill="x")
        tk.Label(input_frame, text="Dummy Workshop Item URL/ID:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        self.dummy_url_entry = tk.Entry(input_frame, textvariable=self.dummy_workshop_url, width=60)
        self.dummy_url_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        tk.Label(input_frame, text="GitHub Gist Raw URL (for XML):").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        self.gist_url_entry = tk.Entry(input_frame, textvariable=self.gist_url, width=60)
        self.gist_url_entry.grid(row=1, column=1, sticky="ew", padx=5, pady=2)
        input_frame.grid_columnconfigure(1, weight=1)

        self.download_button = tk.Button(self.root, text="Download & Install Vehicle XML!",
                                         command=self.initiate_download_process, height=2, bg="lightblue")
        self.download_button.pack(pady=10, padx=10, fill="x")

        log_frame = tk.LabelFrame(self.root, text="Log", padx=5, pady=5)
        log_frame.pack(pady=10, padx=10, fill="both", expand=True)
        self.log_area = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=10, state="disabled")
        self.log_area.pack(fill="both", expand=True)

    def add_log_entry(self, message, is_error=False):
        if message is None:
            print(f"DEV_DEBUG: add_log_entry received None. Using empty string.")
            message = ""
        elif not isinstance(message, str):
            print(f"DEV_DEBUG: add_log_entry received non-string: type={type(message)}, value='{message}'. Attempting str().")
            try:
                message = str(message)
            except Exception as e_str_conv:
                print(f"DEV_DEBUG: Error converting message to string in add_log_entry: {e_str_conv}. Using fallback.")
                message = f"[Unstringable message type: {type(message)}]"
        
        if not (hasattr(self.root, 'winfo_exists') and self.root.winfo_exists()):
            print(f"CONSOLE ECHO (GUI GONE): {message.strip()}")
            return

        self.log_area.configure(state="normal")
        tag_name = "error_tag" if is_error else "info_tag"
        self.log_area.tag_configure("error_tag", foreground="red")
        self.log_area.tag_configure("info_tag", foreground="black")
        
        try:
            self.log_area.insert(tk.END, message + "\n", tag_name)
        except tk.TclError as e_tcl:
            print(f"DEV_DEBUG: TclError during log_area.insert: {e_tcl}. Message: '{message}'")
        except Exception as e_gen_insert:
            print(f"DEV_DEBUG: Unexpected error during log_area.insert: {e_gen_insert}. Message: '{message}'")
            traceback.print_exc()

        self.log_area.configure(state="disabled")
        self.log_area.see(tk.END)
        print(f"CONSOLE ECHO ({'ERROR' if is_error else 'INFO'}): {message.strip()}")

    def load_config_values(self):
        if os.path.exists(CONFIG_FILE):
            self.config.read(CONFIG_FILE)
            self.steam_workshop_base_path.set(self.config.get("Paths", "SteamWorkshopContent", fallback=""))
            self.add_log_entry("Configuration loaded.")
        else:
            self.add_log_entry("Config file not found. Please set the Steam Workshop Content path.")

    def save_config_values(self):
        if not self.config.has_section("Paths"):
            self.config.add_section("Paths")
        self.config.set("Paths", "SteamWorkshopContent", self.steam_workshop_base_path.get())
        with open(CONFIG_FILE, "w") as configfile:
            self.config.write(configfile)
        self.add_log_entry("Configuration saved.")

    def ensure_initial_config(self):
        current_path = self.steam_workshop_base_path.get()
        if not current_path or not os.path.isdir(current_path):
            if hasattr(self.root, 'winfo_exists') and self.root.winfo_exists():
                messagebox.showinfo("Initial Setup",
                                    "Please select your Stormworks Workshop content folder.\n"
                                    f"Example: C:\\...\\Steam\\steamapps\\workshop\\content\\{STORMWORKS_APP_ID}")
                self.select_workshop_folder(force_save_on_selection=True)

    def select_workshop_folder(self, force_save_on_selection=False):
        common_paths = [
            os.path.join("C:\\Program Files (x86)\\Steam\\steamapps\\workshop\\content", STORMWORKS_APP_ID),
            os.path.join("C:\\Program Files\\Steam\\steamapps\\workshop\\content", STORMWORKS_APP_ID),
            os.path.join(os.path.expanduser("~"), ".steam\\steam\\steamapps\\workshop\\content", STORMWORKS_APP_ID)
        ]
        initial_dir_to_try = next((path for path in common_paths if os.path.exists(path)), os.path.expanduser("~"))

        folder_selected = filedialog.askdirectory(initialdir=initial_dir_to_try,
                                                  title=f"Select Stormworks Workshop Folder ({STORMWORKS_APP_ID})")
        if folder_selected:
            folder_selected = os.path.normpath(folder_selected)
            if not (folder_selected.endswith(os.sep + STORMWORKS_APP_ID) or folder_selected == STORMWORKS_APP_ID):
                 confirm = messagebox.askyesno("Path Confirmation",
                                            f"The selected path:\n'{folder_selected}'\n"
                                            f"doesn't look like the specific Stormworks content folder (e.g., ...\\{STORMWORKS_APP_ID}).\n"
                                            "Is this correct?")
                 if not confirm:
                    self.add_log_entry("Workshop path selection cancelled.")
                    if force_save_on_selection and not self.steam_workshop_base_path.get():
                        if messagebox.askyesno("Exit Application?", "The workshop path is crucial and was not set. Exit?"):
                            self.root.quit()
                    return

            self.steam_workshop_base_path.set(folder_selected)
            self.save_config_values()
        elif force_save_on_selection and not self.steam_workshop_base_path.get():
            if hasattr(self.root, 'winfo_exists') and self.root.winfo_exists():
                messagebox.showerror("Path Required", "Steam Workshop Content path is required to use this tool.")
            self.root.quit()

    def parse_workshop_id(self, url_or_id_input):
        if not url_or_id_input: return None
        url_match = re.search(r"id=(\d+)", url_or_id_input)
        if url_match:
            return url_match.group(1)
        id_match = re.fullmatch(r"(\d+)", url_or_id_input.strip())
        if id_match:
            return id_match.group(1)
        return None

    def initiate_download_process(self):
        self.download_button.config(state="disabled", text="Processing...")
        self.log_area.configure(state="normal")
        self.log_area.delete(1.0, tk.END)
        self.log_area.configure(state="disabled")

        self.q.put((self._update_gui_log, ("--- Starting Installation Process ---", False)))
        self.q.put((self._update_gui_log, ("WARNING: This tool modifies local Steam Workshop files. Steam might revert these changes.", False)))

        worker_thread = threading.Thread(target=self.perform_download_and_install, daemon=True)
        worker_thread.start()

    def process_task_queue(self):
        try:
            while True:
                task_item = self.q.get_nowait()
                if callable(task_item):
                    task_item()
                elif isinstance(task_item, tuple) and len(task_item) == 2 and callable(task_item[0]):
                    func_to_call, args_for_func = task_item
                    if isinstance(args_for_func, tuple):
                        func_to_call(*args_for_func)
                    else:
                        print(f"QUEUE_WARN: Args for {func_to_call} not a tuple: {args_for_func}. Calling with single arg.")
                        func_to_call(args_for_func)
                else:
                    print(f"QUEUE_ERROR: Unhandled task structure: {task_item}")
        except queue.Empty:
            pass
        except Exception as e_queue:
            print(f"QUEUE_ERROR: Exception in process_task_queue: {e_queue}")
            traceback.print_exc()

        if hasattr(self.root, 'winfo_exists') and self.root.winfo_exists():
            self.root.after(100, self.process_task_queue)

    def _update_gui_log(self, message_text, is_error_flag=False):
        self.add_log_entry(message_text, is_error_flag)

    def _update_gui_button_state(self, new_button_state, new_button_text):
        if not (hasattr(self.root, 'winfo_exists') and self.root.winfo_exists()):
            return
        self.download_button.config(state=new_button_state, text=new_button_text)
        print(f"CONSOLE (BUTTON_UPDATE): State='{new_button_state}', Text='{new_button_text}'")

    def perform_download_and_install(self):
        print("WORKER: Starting vehicle installation.")
        try:
            workshop_content_dir = self.steam_workshop_base_path.get()
            dummy_item_input = self.dummy_workshop_url.get()
            gist_xml_url = self.gist_url.get()

            if not all([workshop_content_dir, dummy_item_input, gist_xml_url]):
                print("WORKER_ERROR: Missing one or more input fields.")
                self.q.put((self._update_gui_log, ("Error: All input fields are required.", True)))
                return

            if not os.path.isdir(workshop_content_dir):
                print(f"WORKER_ERROR: Invalid Steam Workshop path: {workshop_content_dir}")
                self.q.put((self._update_gui_log, (f"Error: Steam Workshop path is invalid: '{workshop_content_dir}'", True)))
                return

            item_id = self.parse_workshop_id(dummy_item_input)
            if not item_id:
                print(f"WORKER_ERROR: Could not parse Workshop ID from '{dummy_item_input}'.")
                self.q.put((self._update_gui_log, (f"Error: Could not extract Workshop ID from '{dummy_item_input}'.", True)))
                return
            self.q.put((self._update_gui_log, (f"Using Workshop ID: {item_id}", False)))

            item_folder_path = os.path.normpath(os.path.join(workshop_content_dir, item_id))
            print(f"WORKER: Target folder: {item_folder_path}")

            if not os.path.isdir(item_folder_path):
                print(f"WORKER_ERROR: Workshop item folder not found: {item_folder_path}")
                error_msg = (f"Error: Workshop item folder not found at:\n{item_folder_path}\n"
                             "Ensure you are subscribed to the dummy item and it has downloaded.")
                self.q.put((self._update_gui_log, (error_msg, True)))
                return
            self.q.put((self._update_gui_log, (f"Found workshop item folder: {item_folder_path}", False)))

            self.q.put((self._update_gui_log, (f"Fetching vehicle XML from: {gist_xml_url}", False)))
            try:
                response = requests.get(gist_xml_url, timeout=20)
                response.raise_for_status()
                vehicle_xml_data = response.text
                print(f"WORKER: XML fetched (length: {len(vehicle_xml_data)}).")
                self.q.put((self._update_gui_log, ("Vehicle XML fetched successfully.", False)))
            except requests.Timeout:
                print(f"WORKER_ERROR: Timeout fetching Gist XML: {gist_xml_url}")
                self.q.put((self._update_gui_log, (f"Error: Timeout fetching Gist XML.", True)))
                return
            except requests.RequestException as e_req:
                print(f"WORKER_ERROR: Network error fetching Gist XML: {e_req}")
                self.q.put((self._update_gui_log, (f"Error fetching Gist XML: {e_req}", True)))
                return

            self.q.put((self._update_gui_log, ("Validating XML structure...", False)))
            try:
                if not vehicle_xml_data.strip().startswith("<?xml"):
                    print("WORKER_ERROR: Gist content doesn't start with '<?xml'.")
                    self.q.put((self._update_gui_log, ("Error: Gist content does not appear to be valid XML.", True)))
                    return

                xml_root = ET.fromstring(vehicle_xml_data) # Validate it's well-formed XML
                if xml_root.tag != "vehicle":
                    print("WORKER_ERROR: XML root tag is not '<vehicle>'.")
                    self.q.put((self._update_gui_log, ("Error: XML is not a valid Stormworks vehicle file (missing <vehicle> root).", True)))
                    return
                # No longer need to parse 'creation_name' or 'workshop_prev'
                self.q.put((self._update_gui_log, ("XML structure appears valid.", False)))

            except ET.ParseError as e_xml_parse:
                print(f"WORKER_ERROR: Error parsing Gist XML: {e_xml_parse}")
                self.q.put((self._update_gui_log, (f"Error parsing vehicle XML: {e_xml_parse}", True)))
                return

            target_xml_file = os.path.join(item_folder_path, "vehicle.xml")
            print(f"WORKER: Attempting to write to {target_xml_file}")
            try:
                with open(target_xml_file, "w", encoding="utf-8") as f:
                    f.write(vehicle_xml_data)
                self.q.put((self._update_gui_log, (f"Successfully updated: {target_xml_file}", False)))
            except IOError as e_io:
                print(f"WORKER_ERROR: Error writing vehicle.xml: {e_io}")
                self.q.put((self._update_gui_log, (f"Error writing vehicle.xml to workshop folder: {e_io}", True)))
                return

            self.q.put((self._update_gui_log, ("Vehicle XML installed. The existing preview image of the dummy item will be used.", False)))
            self.q.put((self._update_gui_log, ("--- Installation Complete! ---", False)))
            print("WORKER: Installation process seems complete.")

        except Exception as e_unexpected:
            print(f"WORKER_ERROR: An unexpected error occurred: {e_unexpected}")
            traceback.print_exc()
            self.q.put((self._update_gui_log, (f"An critical unexpected error occurred: {e_unexpected}", True)))
        finally:
            print("WORKER: Reached finally block. Queueing button reset.")
            self.q.put((self._update_gui_button_state, ("normal", "Download & Install Vehicle XML!")))

if __name__ == "__main__":
    main_window = tk.Tk()
    app_instance = StormworksInstallerApp(main_window)
    main_window.mainloop()