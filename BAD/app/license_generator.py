import os
import platform
import subprocess
import uuid
import hashlib
from datetime import datetime

SECRET_SALT = "PAHLAWAN_KEBUN_REAKTIVASI_2026_FOXCOM_SUPER_KEY"
LICENSE_FILE_NAME = "license.key"


def get_hardware_id():
    """Generate the same HWID that the main application uses."""
    try:
        if platform.system().lower() == "windows":
            for cmd in (["wmic", "csproduct", "get", "uuid"], ["wmic", "bios", "get", "serialnumber"]):
                try:
                    output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
                    lines = [line.strip() for line in output.splitlines() if line.strip()]
                    if len(lines) >= 2 and lines[1].upper() not in {"UUID", "SERIALNUMBER"}:
                        return lines[1].upper()
                except Exception:
                    continue

        node_name = platform.node().strip()
        mac = uuid.getnode()
        raw = f"{node_name}-{mac:012X}" if node_name else f"{mac:012X}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()[:32]
    except Exception:
        return hashlib.sha256(platform.node().encode("utf-8")).hexdigest().upper()[:32]


def normalize_expiry_date(expiry_date):
    if isinstance(expiry_date, datetime):
        return expiry_date.strftime("%Y-%m-%d")
    expiry_date = expiry_date.strip()
    try:
        parsed = datetime.strptime(expiry_date, "%Y-%m-%d")
        return parsed.strftime("%Y-%m-%d")
    except ValueError:
        raise ValueError("Format tanggal harus YYYY-MM-DD")


def generate_signature(hwid, expiry_date):
    hwid_clean = hwid.strip().upper()
    expiry_date_str = normalize_expiry_date(expiry_date)
    raw = f"{hwid_clean}|{expiry_date_str}|{SECRET_SALT}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


def generate_license(hwid, expiry_date, user_name=None, license_type=None, note=None):
    expiry_date_str = normalize_expiry_date(expiry_date)
    signature = generate_signature(hwid, expiry_date_str)
    license_key = f"{expiry_date_str}-{signature}"
    return {
        "hwid": hwid.strip(),
        "expiry_date": expiry_date_str,
        "signature": signature,
        "license_key": license_key,
        "user_name": user_name or "",
        "license_type": license_type or "",
        "note": note or "",
    }


def save_license_file(license_key, path=None):
    if path is None:
        path = os.path.join(os.getcwd(), LICENSE_FILE_NAME)
    with open(path, "w", encoding="utf-8") as f:
        f.write(license_key)
    return path


def prompt_text(prompt, default=None):
    value = input(f"{prompt}{' [' + default + ']' if default else ''}: ").strip()
    return value if value else (default or "")


def main():
    last_hwid = get_hardware_id()
    last_license = None
    print("=== Kebun Reaktivasi License Generator ===")
    print("Gunakan HWID yang sama dengan aplikasi utama agar lisensi kompatibel.")
    print()

    while True:
        print("1. Generate license")
        print("2. Input HWID manual")
        print("3. Simpan license file")
        print("4. Exit")
        choice = input("Pilih aksi [1-4]: ").strip()

        if choice == "1":
            print(f"Current HWID       : {last_hwid}")
            manual = input("Gunakan HWID ini? (y/n) ").strip().lower()
            if manual == "n":
                last_hwid = input("Masukkan HWID manual: ").strip().upper()
            expiry = prompt_text("Tanggal expired (YYYY-MM-DD)")
            try:
                expiry = normalize_expiry_date(expiry)
            except ValueError as exc:
                print(f"[ERROR] {exc}")
                continue
            user_name = prompt_text("Nama user (opsional)")
            license_type = prompt_text("Tipe lisensi (opsional)")
            note = prompt_text("Catatan (opsional)")
            result = generate_license(last_hwid, expiry, user_name, license_type, note)
            last_license = result["license_key"]
            print("\nLicense key yang dihasilkan:")
            print(last_license)
            print("Salin key ini ke file license.key di folder aplikasi utama.")
            print()

        elif choice == "2":
            manual_hwid = input("Masukkan HWID target secara manual: ").strip().upper()
            if manual_hwid:
                last_hwid = manual_hwid
                print(f"HWID disimpan: {last_hwid}")
            else:
                print("HWID manual kosong; menggunakan HWID otomatis.")

        elif choice == "3":
            if not last_license:
                print("Belum ada license yang di-generate. Pilih 1 terlebih dahulu.")
                continue
            target_path = prompt_text("Nama file output", LICENSE_FILE_NAME)
            saved_path = save_license_file(last_license, os.path.abspath(target_path))
            print(f"License file disimpan di: {saved_path}")

        elif choice == "4":
            print("Keluar.")
            break

        else:
            print("Pilihan tidak valid. Silakan coba lagi.")


if __name__ == "__main__":
    main()
