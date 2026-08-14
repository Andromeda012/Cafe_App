def add_product(basket, stok_kodu):
    """Ürünü sepete ekler veya mevcut adedini artırır."""

    if not stok_kodu:
        return

    if stok_kodu not in basket:
        basket[stok_kodu] = 1
    else:
        basket[stok_kodu] += 1


def decrease_product(basket, stok_kodu):
    """Ürün adedini azaltır. Adet sıfır olursa ürünü siler."""

    if stok_kodu not in basket:
        return

    basket[stok_kodu] -= 1

    if basket[stok_kodu] <= 0:
        del basket[stok_kodu]


def remove_product(basket, stok_kodu):
    """Ürünü sepetten tamamen kaldırır."""

    if stok_kodu in basket:
        del basket[stok_kodu]

def calculate_total(added_stoks,basket):

    total = 0

    for added_stok in added_stoks:
        stok_total = int(added_stok[1]) * int(basket[added_stok[2]])
        total += stok_total

    return total