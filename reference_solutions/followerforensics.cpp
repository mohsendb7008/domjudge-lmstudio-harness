#include <algorithm>
#include <iostream>
#include <map>
#include <optional>
#include <set>
#include <stack>
#include <vector>

using namespace std;

using int_t = int64_t;

using edge_t = pair<int_t, int_t>;

struct vertex_t {
    int_t label = 0;
    int_t outdegree = 0;
    int_t indegree = 0;
    int_t connections_in = 0;
    int_t connections_out = 0;
};

struct normal_order_in {
    auto key(const vertex_t a) const {
        return tuple{ -a.indegree, -a.outdegree, a.label };
    }
    bool operator()(const vertex_t a, const vertex_t b) const {
        return key(a) < key(b);
    }
};

struct normal_order_out {
    auto key(const vertex_t a) const {
        return tuple{ -a.outdegree, -a.indegree, a.label };
    }
    bool operator()(const vertex_t a, const vertex_t b) const {
        return key(a) < key(b);
    }
};

struct indegree_ascending {
    auto key(const vertex_t a) const {
        return tuple{ a.indegree, a.outdegree, a.label };
    }
    bool operator()(const vertex_t a, const vertex_t b) const {
        return key(a) < key(b);
    }
};

struct outdegree_ascending {
    auto key(const vertex_t a) const {
        return tuple{ a.outdegree, a.indegree, a.label };
    }
    bool operator()(const vertex_t a, const vertex_t b) const {
        return key(a) < key(b);
    }
};

struct union_find {
    int_t components;
    vector<int_t> p;
    union_find(int_t n) : components(n), p(n, -1) {
    }

    int_t find(int_t x) {
        return p[x] < 0 ? x : p[x] = find(p[x]);
    }
    bool unite(int_t x, int_t y) {
        int_t xp = find(x), yp = find(y);
        if (xp == yp) {
            return false;
        }
        if (p[xp] > p[yp]) {
            swap(xp, yp);
        }
        p[xp] += p[yp];
        p[yp] = xp;
        components--;
        return true;
    }
    size_t size(int_t x) {
        return -p[find(x)];
    }
};

struct erdos_miklos_toroczkai {
    vector<vertex_t> sequence;
    set<vertex_t, indegree_ascending> pick_order_in;
    set<vertex_t, outdegree_ascending> pick_order_out;
    set<vertex_t, normal_order_in> ordered_by_in;
    set<vertex_t, normal_order_out> ordered_by_out;
    optional<vector<edge_t>> result{ nullopt };
    union_find uf;

    void insert(const vertex_t &d) {
        if (d.outdegree > 0) {
            pick_order_out.insert(d);
        }
        if (d.indegree > 0) {
            pick_order_in.insert(d);
        }
        if (d.indegree + d.outdegree > 0) {
            ordered_by_in.insert(d);
            ordered_by_out.insert(d);
        }
    }

    void remove(const vertex_t &d) {
        pick_order_in.erase(d);
        pick_order_out.erase(d);
        ordered_by_in.erase(d);
        ordered_by_out.erase(d);
    }

    bool should_pick_indegree() {
        if (pick_order_out.empty()) {
            return true;
        }
        else if (pick_order_in.empty() || outdegree_ascending{}.key(*pick_order_out.begin()) < indegree_ascending{}.key(*pick_order_in.begin())) {
            return false;
        }
        return true;
    }

    erdos_miklos_toroczkai(const vector<vertex_t> &sequence) : sequence(sequence), uf(sequence.size()) {
        int_t m_out = 0, m_in = 0;
        for (const auto d : sequence) {
            insert(d);
            m_out += d.outdegree;
            m_in += d.indegree;
        }

        if (m_out != m_in) {
            return;
        }

        vector<edge_t> edges;
        edges.reserve(m_out);

        while (ssize(edges) < m_out) {
            bool pick_in{ should_pick_indegree() };
            if (pick_in ? pick_order_in.empty() : pick_order_out.empty()) {
                return;
            }
            vertex_t d_n{ pick_in ? *pick_order_in.begin() : *pick_order_out.begin() };
            remove(d_n);

            vector<vertex_t> updates;
            updates.reserve(pick_in ? d_n.indegree : d_n.outdegree);
            while ((pick_in ? d_n.indegree : d_n.outdegree) > 0) {
                if (pick_in ? ordered_by_out.empty() : ordered_by_in.empty()) {
                    return;
                }
                vertex_t d{ pick_in ? *ordered_by_out.begin() : *ordered_by_in.begin() };
                updates.push_back(d);
                remove(d);
                (pick_in ? d_n.indegree : d_n.outdegree)--;
                (pick_in ? d_n.connections_in : d_n.connections_out)++;
            }

            for (auto d : updates) {
                if ((pick_in ? d.outdegree : d.indegree) == 0) {
                    return;
                }
                (pick_in ? d.outdegree : d.indegree)--;
                (pick_in ? d.connections_out : d_n.connections_in)++;
                edges.push_back({ pick_in ? d.label : d_n.label, pick_in ? d_n.label : d.label });
                uf.unite(d.label, d_n.label);
                insert(d);
            }
            insert(d_n);
        }

        if (uf.components == 1) {
            result = edges;
        }
    }
};

int main() {
    int_t n;
    cin >> n;
    vector<vertex_t> sequence(n);
    for (int_t i = 0; i < n; i++) {
        sequence[i].label = i;
    }
    for (int_t i = 0; i < n; i++) {
        cin >> sequence[i].outdegree;
    }
    for (int_t i = 0; i < n; i++) {
        cin >> sequence[i].indegree;
    }

    const auto result{ erdos_miklos_toroczkai(sequence).result };

    if (result.has_value()) {
        vector<vector<int_t>> adj(n);
        for (auto [a, b] : result.value()) {
            adj[a].push_back(b);
        }
        cout << n << " " << result->size() << '\n';
        for (auto [a, b] : result.value()) {
            cout << a + 1 << " " << b + 1 << '\n';
        }
        return 0;
    }
    cout << "impossible" << endl;
    return 0;
}
