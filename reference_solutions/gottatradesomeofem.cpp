#include <iostream>
#include <list>
#include <vector>

using namespace std;
using int_t = int64_t;

struct union_find_t {
    vector<int_t> parent;
    vector<list<int_t>> groups;
    union_find_t(int_t n) : parent(n), groups(n) {
        for (int_t i = 0; i < n; i++) {
            parent[i] = i;
            groups[i].push_back(i);
        }
    }

    int_t find(int_t x) {
        return parent[x] = (x == parent[x] ? x : find(parent[x]));
    }

    bool unite(int_t x, int_t y) {
        int_t xp = find(x);
        int_t yp = find(y);
        if (xp == yp) return false;
        groups[xp].splice(groups[xp].end(), groups[yp]);
        parent[yp] = xp;
        return true;
    }

    int_t size(int_t x) {
        return groups[find(x)].size();
    }
};

int main() {
    int_t n, m, k;
    cin >> n >> m >> k;

    union_find_t uf(n);

    for (int_t i = 0; i < m; i++) {
        int_t a, b;
        cin >> a >> b;
        a--, b--;
        uf.unite(a, b);
    }

    for (int_t i = 0; i < n; i++) {
        if (i == uf.find(i) && uf.size(i) < k) {
            cout << "impossible" << endl;
            return 0;
        }
    }

    vector<int_t> color(n);
    for (int_t i = 0; i < n; i++) {
        if (i == uf.find(i)) {
            int_t j = 0;
            for (auto it = cbegin(uf.groups[i]); it != cend(uf.groups[i]); it++, j++) {
                color[*it] = j % k + 1;
            }
        }
    }

    for (int_t i = 0; i < n; i++) {
        cout << (i ? " " : "") << color[i];
    }
    cout << endl;

    return 0;
}
